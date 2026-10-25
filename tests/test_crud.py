"""Tests du CRUD : création, lecture, modification, suppression, validation, intégrité."""
import pytest
import rdflib

from app.errors import IntegrityError, NotFoundError, ValidationError
from app.services import crud


def test_lecture_avec_recherche_tri_pagination(store):
    r = crud.rechercher("Building", taille=4, tri="hasConsumption", decroissant=True)
    assert r["total"] == 9 and r["pages"] == 3 and len(r["lignes"]) == 4
    assert r["lignes"][0]["id"] == "Factory_Ariana_01"
    assert [l["id"] for l in crud.rechercher("Building", texte="usine")["lignes"]] == [
        "Factory_Ariana_01", "Factory_Sousse_01", "Factory_Tunis_01"]
    assert crud.rechercher("IndustrialBuilding")["total"] == 3          # les sous-classes sont gérées
    assert crud.rechercher("Building", filtres={"type": "Residential"})["total"] == 3


def test_fiche_avec_relations_entrantes(store):
    f = crud.fiche("SolarFarm_Ariana")
    assert f["nom"] == "Ferme solaire de l'Ariana" and f["type"] == "SolarSource"
    assert {r["de"] for r in f["references"]} >= {"Building_Ariana_01", "Factory_Ariana_01", "GridNode_Ariana_01"}
    with pytest.raises(NotFoundError):
        crud.fiche("Inexistant")


def test_creation_insert_data_et_persistance(store):
    op = crud.creer("BatteryStorage", {"hasName": "Batterie Sfax", "hasStorageCapacity": "12,5",
                                       "hasEfficiency": "0.91", "storesEnergy": "SolarEnergy_001"})
    assert op.data["id"] == "Batterie_Sfax" and "INSERT DATA" in op.sparql
    assert crud.fiche("Batterie_Sfax")["donnees"]["hasStorageCapacity"] == 12.5
    # le fichier .owl a été réécrit et reste lisible
    g = rdflib.Graph().parse(store.chemin, format="xml")
    assert any("Batterie_Sfax" in str(s) for s in g.subjects())


def test_identifiant_unique(store):
    crud.creer("User", {"hasName": "Test", "hasEmail": "t@x.tn", "hasRole": "lecteur"}, "User_T")
    with pytest.raises(ValidationError, match="existe déjà"):
        crud.creer("User", {"hasName": "Autre", "hasEmail": "o@x.tn", "hasRole": "lecteur"}, "User_T")
    # nom identique sans identifiant imposé : un suffixe est ajouté
    a = crud.creer("User", {"hasName": "Doublon", "hasEmail": "d1@x.tn", "hasRole": "lecteur"}).data["id"]
    b = crud.creer("User", {"hasName": "Doublon", "hasEmail": "d2@x.tn", "hasRole": "lecteur"}).data["id"]
    assert a != b


@pytest.mark.parametrize("donnees,message", [
    ({"hasName": "X", "hasEfficiency": "1.5"}, "entre 0 et 1"),
    ({"hasName": "X", "hasStorageCapacity": "-4"}, "positif"),
    ({"hasName": "X", "hasStorageCapacity": "abc"}, "nombre"),
    ({"hasName": "X", "hasConsumption": "3"}, "ne s'applique pas"),
    ({"hasEfficiency": "0.5"}, "obligatoire"),
    ({"hasName": "X", "storesEnergy": "ESPRIT"}, "n'existe pas ou n'est pas"),
])
def test_validation_batterie(store, donnees, message):
    with pytest.raises(ValidationError, match=message):
        crud.creer("BatteryStorage", donnees)


def test_validation_autres_types(store):
    with pytest.raises(ValidationError, match="supérieure|dépasser"):
        crud.creer("SolarSource", {"hasName": "S", "hasCapacity": 10, "hasPowerOutput": 12})
    with pytest.raises(ValidationError, match="date valide"):
        crud.creer("GridNode", {"hasName": "N", "hasInstallationDate": "pas une date"})
    with pytest.raises(ValidationError, match="e-mail"):
        crud.creer("User", {"hasName": "U", "hasEmail": "pas-un-mail"})
    with pytest.raises(ValidationError, match="déjà utilisée"):
        crud.creer("User", {"hasName": "U", "hasEmail": "ahmed.bensalah@smartgrid.tn"})
    ok = crud.creer("GridNode", {"hasName": "Nœud Gabès", "hasInstallationDate": "2024-05-17", "hasVoltage": 30,
                                 "connectedTo": ["GridNode_Tunis_01"]})
    assert "xsd:dateTime" in ok.sparql
    # connectedTo est symétrique : la réciproque est écrite aussi
    assert "N_ud_Gab_s" not in ok.data["id"]
    assert ok.data["id"] in [x["id"] for x in crud.fiche("GridNode_Tunis_01")["relations"]["connectedTo"]]


def test_modification_prerempli_et_delete_insert(store):
    op = crud.modifier("Battery_Tunis_01", {"hasStorageCapacity": "15", "hasName": "Batterie principale"})
    assert "DELETE" in op.sparql and "INSERT" in op.sparql
    f = crud.fiche("Battery_Tunis_01")
    assert f["donnees"]["hasStorageCapacity"] == 15.0 and f["nom"] == "Batterie principale"
    with pytest.raises(ValidationError):
        crud.modifier("Battery_Tunis_01", {"hasEfficiency": 2})
    with pytest.raises(ValidationError, match="dépasser"):
        crud.modifier("SolarFarm_Tunis", {"hasCapacity": 10})   # production réelle 42.5 > 10


def test_suppression_integrite_et_cascade(store):
    with pytest.raises(IntegrityError) as exc:
        crud.supprimer("SolarFarm_Tunis")
    assert any(r["de"] == "ESPRIT" for r in exc.value.references)
    op = crud.supprimer("SolarFarm_Tunis", cascade=True)
    assert op.data["liens_retires"] >= 2
    assert not crud.existe("SolarFarm_Tunis")
    assert "suppliedBy" not in crud.fiche("ESPRIT")["relations"]
    # la liste owl:AllDifferent reste valide (rdflib recharge sans erreur)
    rdflib.Graph().parse(store.chemin, format="xml")
    assert crud.supprimer("Substation_Sousse").data["liens_retires"] == 0      # personne ne la référence


def test_formulaire_dynamique(store):
    champs = {c["nom"]: c for c in crud.champs_formulaire("Building")}
    assert champs["hasConsumption"]["kind"] == "decimal" and champs["hasConsumption"]["min"] == 0
    assert "SolarFarm_Tunis" in champs["suppliedBy"]["options"] and "ESPRIT" not in champs["suppliedBy"]["options"]
    assert champs["hasStorage"]["multi"] and not champs["suppliedBy"]["multi"]
    assert champs_roles(store) == ["admin", "lecteur"]


def champs_roles(store):
    return [c for c in crud.champs_formulaire("User") if c["nom"] == "hasRole"][0]["options"]
