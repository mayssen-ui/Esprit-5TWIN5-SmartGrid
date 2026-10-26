"""Tests du module TALN (spaCy + scikit-learn) : lemmes, dépendances, entités, similarité."""
from app.ai import nl2sparql, nlp
from app.ai.vocab import classes_dans, props_dans


def test_pipeline_spacy_charge_et_analyse():
    a = nlp.analyser("Quels bâtiments sont alimentés par une ferme solaire à Tunis ?")
    assert "alimenter" in a.lemmes and "batiment" in a.lemmes            # lemmatisation
    assert ("Tunis", "LOC") in a.entites                                    # reconnaissance d'entités nommées
    assert any(cat == "VERB" for _, _, cat in a.pos)                        # étiquetage grammatical


def test_reperage_des_classes_par_lemmes():
    # pluriels, accords et conjugaisons sont gérés par le lemmatiseur
    assert {c for c, _, _ in classes_dans("Combien de sources éoliennes ?")} == {"WindSource"}
    assert {c for c, _, _ in classes_dans("Les usines et les batteries")} == {"IndustrialBuilding", "BatteryStorage"}
    assert [p for p, _, _ in props_dans("la consommation totale")] == ["hasConsumption"]


def test_dependances_complement_d_agent():
    a = nlp.analyser("Quels bâtiments sont alimentés par une ferme solaire ?")
    d, f = nlp.complement_agent(a)
    assert a.texte[d:f].endswith("ferme solaire")


def test_verbes_conjugues(store):
    for phrase in ("Ajoutez une batterie nommée Batterie Test de capacité 5",
                   "Je voudrais créer une batterie nommée Batterie Test de capacité 5"):
        r = nl2sparql.repondre(phrase)
        assert r["regle"] == "ajout" and r["confirmation_requise"], phrase


def test_similarite_tfidf_avec_le_catalogue(store):
    r = nl2sparql.repondre("Quel est le bilan entre la production et la consommation pour chaque endroit du réseau ?")
    assert r["niveau"] == "similarite" and r["regle"] == "bilan_par_noeud" and r["resultat"]["rows"]
    assert nl2sparql.repondre("Quel temps fait-il demain à Paris ?")["erreur"]


def test_aucun_appel_a_un_llm():
    import pathlib
    import re
    code = "".join(p.read_text(encoding="utf-8") for p in pathlib.Path(nl2sparql.__file__).parent.glob("*.py"))
    assert not re.search(r"import anthropic|import openai|google\.generativeai", code)
