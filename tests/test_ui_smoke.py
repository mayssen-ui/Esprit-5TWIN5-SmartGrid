"""Tests de fumée de l'interface Streamlit : chaque page se charge sans erreur (AppTest)."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

RACINE = Path(__file__).resolve().parent.parent
PAGES = sorted((RACINE / "app" / "ui" / "pages").glob("*.py"))
ADMIN = {"id": "User_Ahmed", "nom": "Ahmed Ben Salah", "email": "ahmed.bensalah@smartgrid.tn", "role": "admin"}


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.stem)
def test_page_se_charge(store, page):
    at = AppTest.from_file(str(page), default_timeout=60)
    at.session_state["utilisateur"] = ADMIN
    at.run()
    assert not at.exception, [e.value for e in at.exception]


def test_page_sans_connexion_demande_de_se_connecter(store):
    at = AppTest.from_file(str(RACINE / "app" / "ui" / "pages" / "gestion.py"), default_timeout=60).run()
    assert not at.exception and any("Connectez-vous" in w.value for w in at.warning)


def test_lecteur_en_lecture_seule(store):
    at = AppTest.from_file(str(RACINE / "app" / "ui" / "pages" / "gestion.py"), default_timeout=60)
    at.session_state["utilisateur"] = {**ADMIN, "role": "lecteur"}
    at.run()
    assert not at.exception and any("lecture seule" in i.value or "lecteur" in i.value for i in at.info)


def test_poser_une_question(store):
    at = AppTest.from_file(str(RACINE / "app" / "ui" / "pages" / "question.py"), default_timeout=60)
    at.session_state["utilisateur"] = ADMIN
    at.run()
    at.text_input(key="question").set_value("Combien de sources éoliennes y a-t-il ?").run()
    [b for b in at.button if b.label == "Poser la question"][0].click().run()
    assert not at.exception and any("2 sources éoliennes" in s.value for s in at.success)
