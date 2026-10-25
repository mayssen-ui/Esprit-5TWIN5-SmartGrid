"""Fixtures communes : chaque test travaille sur une copie jetable de l'ontologie."""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

from app.sparql.store import RdflibStore, set_store  # noqa: E402


@pytest.fixture()
def store(tmp_path, monkeypatch):
    """Magasin rdflib sur une copie temporaire de data/SmartGrid-Semantic.owl."""
    copie = tmp_path / "SmartGrid-Semantic.owl"
    shutil.copy(RACINE / "data" / "SmartGrid-Semantic.owl", copie)
    monkeypatch.setenv("SG_OWL_PATH", str(copie))
    monkeypatch.setenv("SG_DATA_DIR", str(tmp_path / "donnees"))   # historique et journaux isolés
    monkeypatch.setenv("SG_API_AUTH", "true")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    s = RdflibStore(copie)
    set_store(s)
    yield s
    set_store(None)


@pytest.fixture()
def client(store):
    from fastapi.testclient import TestClient

    from app.api.main import app

    return TestClient(app)


def _entetes(client, email, mdp):
    r = client.post("/api/auth/login", data={"username": email, "password": mdp})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["access_token"]}


@pytest.fixture()
def admin(client):
    return _entetes(client, "ahmed.bensalah@smartgrid.tn", "admin123")


@pytest.fixture()
def lecteur(client):
    return _entetes(client, "salma.trabelsi@smartgrid.tn", "lecteur123")
