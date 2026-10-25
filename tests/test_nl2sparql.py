"""Tests de la traduction langage humain -> SPARQL et de ses garde-fous."""
import json

import pytest

from app.ai import nl2sparql
from app.services import crud


def poser(question, **kw):
    return nl2sparql.repondre(question, utiliser_llm=False, **kw)


def test_lister_les_batiments(store):
    r = poser("Citer les différents bâtiments")
    assert r["niveau"] == "regles" and r["execute"] and len(r["resultat"]["rows"]) == 9
    assert "SELECT" in r["sparql"] and "J'ai trouvé 9" in r["message"]


def test_batiments_alimentes_par_ferme_solaire(store):
    r = poser("Quels bâtiments sont alimentés par une ferme solaire ?")
    noms = {x["nom_batiment"] for x in r["resultat"]["rows"]}
    assert "ESPRIT" in noms and "Usine Tunis 01" not in noms and len(noms) == 5


def test_source_renouvelable_et_non_renouvelable(store):
    assert len(poser("Citer les bâtiments alimentés par une source d'énergie renouvelable")["resultat"]["rows"]) == 6
    assert "Il y a 1 bâtiment" in poser("Combien de bâtiments sont alimentés par une source non renouvelable ?")["message"]


def test_comptage_fr_et_en(store):
    assert "Il y a 2 sources éoliennes" in poser("Combien de sources éoliennes y a-t-il ?")["message"]
    assert "Il y a 2 sources éoliennes" in poser("How many wind sources are there?")["message"]


def test_agregat(store):
    r = poser("Quelle est la consommation totale des bâtiments industriels ?")
    assert r["resultat"]["rows"][0]["total"] == pytest.approx(35.5)
    assert "35.5" in r["message"] and "industriels" in r["message"]
    assert poser("Quelle est la moyenne de l'efficacité des batteries")["resultat"]["rows"][0]["moyenne"] == pytest.approx(0.9)


def test_valeur_top_et_relations(store):
    assert "10" in poser("Quelle est la capacité de la batterie Tunis 01 ?")["message"]
    top = poser("Top 3 des plus gros consommateurs")["resultat"]["rows"]
    assert [x["nom"] for x in top][0] == "Usine Ariana 01" and len(top) == 3
    assert len(poser("Quels utilisateurs possèdent des bâtiments industriels ?")["resultat"]["rows"]) == 3
    assert len(poser("Quels bâtiments ont une batterie ?")["resultat"]["rows"]) == 3
    assert len(poser("Liste les nœuds connectés")["resultat"]["rows"]) == 2


def test_ajout_exige_une_confirmation(store):
    r = poser("Ajouter une batterie nommée Batterie Sousse de capacité 12")
    assert r["confirmation_requise"] and not r["execute"]
    assert "INSERT DATA" in r["sparql"] and '"12.0"^^xsd:decimal' in r["sparql"]
    assert not crud.existe("Batterie_Sousse")                      # rien n'est écrit sans confirmation
    r = poser("Ajouter une batterie nommée Batterie Sousse de capacité 12", confirmer=True)
    assert r["execute"] and crud.fiche("Batterie_Sousse")["donnees"]["hasStorageCapacity"] == 12.0


def test_ecriture_refusee_au_lecteur_et_validation(store):
    r = poser("Supprimer le bâtiment ESPRIT", confirmer=True, peut_ecrire=False)
    assert "lecteur" in r["erreur"] and crud.existe("ESPRIT")
    r = poser("Ajouter une batterie nommée Bad d'efficacité 1.5")
    assert r["erreur"] and "entre 0 et 1" in r["erreur"]
    r = poser("Modifier la capacité de la batterie Batterie Tunis 01 à 15", confirmer=True)
    assert r["execute"] and crud.fiche("Battery_Tunis_01")["donnees"]["hasStorageCapacity"] == 15.0


@pytest.mark.parametrize("requete,message", [
    ("DROP ALL", "INSERT et DELETE"),
    ("CLEAR GRAPH <http://x>", "INSERT et DELETE"),
    ("SELECT * WHERE { SERVICE <http://exemple.org/sparql> { ?s ?p ?o } }", "SERVICE"),
    ("SELECT ?s WHERE { ?s ?p ?o", "pas valide"),
    ("DESCRIBE <http://exemple.org/x>", "SELECT, ASK et CONSTRUCT"),
])
def test_garde_fous(store, requete, message):
    r = nl2sparql.repondre(sparql=requete, confirmer=True)
    assert message in r["erreur"] and not r["execute"]


def test_limite_de_resultats_et_requete_corrigee(store, monkeypatch):
    monkeypatch.setenv("SG_MAX_RESULTS", "5")
    r = nl2sparql.repondre(sparql="SELECT ?s ?p ?o WHERE { ?s ?p ?o }")
    assert r["tronque"] and len(r["resultat"]["rows"]) == 5 and r["sparql"].rstrip().endswith("LIMIT 5")
    r = nl2sparql.repondre(sparql="ASK { sg:ESPRIT sg:hasName ?n }")
    assert r["resultat"]["boolean"] is True


def test_sans_modele_ni_llm_message_clair(store):
    r = poser("Quel temps fait-il demain à Paris ?")
    assert "pas compris" in r["erreur"]


def test_journal(store, tmp_path, monkeypatch):
    from app.ai import guardrails

    poser("Combien de batteries ?")
    entrees = guardrails.lire_journal(5)
    assert entrees and entrees[0]["question"] == "Combien de batteries ?" and json.dumps(entrees[0])
