"""Tests du CRUD complexe (transactions) et des requêtes croisées."""
import pytest

from app.errors import NotFoundError, ValidationError
from app.services import complex_ops, crud
from app.sparql.queries import CATALOGUE, PAR_ID


def test_toutes_les_requetes_croisees_s_executent(store):
    assert len(CATALOGUE) >= 9
    for q in CATALOGUE:
        res = store.query(q.sparql)
        assert res.vars, q.id


@pytest.mark.parametrize("requete_id,attendu", [
    ("batiments_sources", 7),
    ("batiments_batteries", 3),
    ("utilisateurs_industriels", 3),
    ("noeuds_sources", 6),
    ("postes_noeuds", 3),
    ("batiments_renouvelables", 6),
    ("conso_superieure_production", 1),
    ("noeuds_connectes", 2),
    ("batiments_sans_source", 2),
])
def test_resultats_attendus(store, requete_id, attendu):
    assert len(store.query(PAR_ID[requete_id].sparql)) == attendu


def test_property_path_et_having(store):
    res = store.query(PAR_ID["noeuds_atteignables"].sparql)
    assert {r["nom_atteint"] for r in res.rows} == {"Nœud Ariana 01", "Nœud Sousse 01"}
    h = store.query(PAR_ID["sources_plusieurs_batiments"].sparql).rows
    assert h[0]["nb_batiments"] == 3


def test_creer_batiment_lie_en_une_transaction(store):
    op = complex_ops.creer_batiment_lie("CommercialBuilding", {"hasName": "Magasin Test", "hasConsumption": 1.5},
                                        "SolarFarm_Tunis", "GridNode_Tunis_01", "Battery_Tunis_01")
    f = crud.fiche(op.data["id"])
    assert f["relations"]["suppliedBy"][0]["id"] == "SolarFarm_Tunis"
    assert f["relations"]["locatedIn"][0]["id"] == "GridNode_Tunis_01"
    assert f["relations"]["consumes"][0]["id"] == "SolarEnergy_001"


def test_rollback_en_cas_d_erreur(store):
    avant = len(store.snapshot())
    with pytest.raises(NotFoundError):
        complex_ops.creer_batiment_lie("CommercialBuilding", {"hasName": "Fantôme"}, "SourceInconnue", None)
    with pytest.raises(ValidationError):
        complex_ops.creer_batiment_lie("CommercialBuilding", {"hasName": "Fantôme", "hasConsumption": -3},
                                       "SolarFarm_Tunis", "GridNode_Tunis_01")
    assert len(store.snapshot()) == avant and not crud.existe("Fant_me")


def test_reaffecter_et_supprimer_source(store):
    complex_ops.reaffecter_batiment("ESPRIT", "WindFarm_Bizerte")
    f = crud.fiche("ESPRIT")
    assert f["relations"]["suppliedBy"] == [{"id": "WindFarm_Bizerte", "nom": "Parc éolien de Bizerte"}]
    assert f["relations"]["consumes"][0]["id"] == "WindEnergy_001"
    op = complex_ops.supprimer_source_detachee("SolarFarm_Ariana")
    assert set(op.data["batiments_detaches"]) == {"Building_Ariana_01", "Factory_Ariana_01", "House_Ariana_01"}
    assert not crud.existe("SolarFarm_Ariana")
    assert len(store.query(PAR_ID["batiments_sans_source"].sparql)) == 5


def test_affecter_utilisateur_a_plusieurs_batiments(store):
    complex_ops.affecter_utilisateur("User_Leila", ["ESPRIT", "House_Tunis_01"])
    owns = [x["id"] for x in crud.fiche("User_Leila")["relations"]["owns"]]
    assert {"Factory_Sousse_01", "ESPRIT", "House_Tunis_01"} <= set(owns)
    complex_ops.affecter_utilisateur("User_Leila", ["ESPRIT"], remplacer=True)
    assert [x["id"] for x in crud.fiche("User_Leila")["relations"]["owns"]] == ["ESPRIT"]
    with pytest.raises(ValidationError):
        complex_ops.affecter_utilisateur("User_Leila", ["SolarFarm_Tunis"])
