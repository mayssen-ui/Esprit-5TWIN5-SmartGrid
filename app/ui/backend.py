"""Accès aux données pour l'interface : via l'API REST (front -> back) ou directement via les services.

`SG_UI_MODE` : `api` (toujours l'API), `direct` (services Python), `auto` (défaut : API si elle répond, sinon direct).
`SG_API_URL` : adresse de l'API (défaut http://localhost:8000).

Les pages « Gérer les éléments » et « Poser une question » passent par cette façade ; leur code est identique
dans les deux modes.
"""
from __future__ import annotations

import os
from typing import Any

import httpx
import streamlit as st

from app.ai import nl2sparql
from app.errors import (ForbiddenError, IntegrityError, NotFoundError, SmartGridError, ValidationError)
from app.services import crud
from app.services.common import Op

# Fonctions pures réutilisées telles quelles
requete_liste = crud.requete_liste
MONO_VALUEES = crud.MONO_VALUEES

API_URL = os.getenv("SG_API_URL", "http://localhost:8000").rstrip("/")


def mode() -> str:
    """Retourne « api » ou « direct » (détecté une fois par session en mode auto)."""
    voulu = os.getenv("SG_UI_MODE", "auto").lower()
    if voulu in ("api", "direct"):
        return voulu
    if "mode_ui" not in st.session_state:
        try:
            ok = httpx.get(API_URL + "/", timeout=1.0).status_code == 200
        except httpx.HTTPError:
            ok = False
        st.session_state["mode_ui"] = "api" if ok else "direct"
    return st.session_state["mode_ui"]


def redetecter() -> None:
    st.session_state.pop("mode_ui", None)


def obtenir_jeton(email: str, mot_de_passe: str) -> None:
    """Mode API : se connecte à l'API avec les mêmes identifiants et garde le jeton en session."""
    if mode() != "api":
        return
    r = httpx.post(f"{API_URL}/api/auth/login", data={"username": email, "password": mot_de_passe}, timeout=10)
    if r.status_code == 200:
        st.session_state["jeton"] = r.json()["access_token"]


def _appel(methode: str, chemin: str, **kw) -> Any:
    entetes = {"Authorization": f"Bearer {st.session_state.get('jeton', '')}"}
    try:
        r = httpx.request(methode, API_URL + chemin, headers=entetes, timeout=30, **kw)
    except httpx.HTTPError as exc:
        raise SmartGridError(f"L'API ne répond pas ({API_URL}). Lancez : uvicorn app.api.main:app") from exc
    if r.status_code < 400:
        return r.json()
    try:
        corps = r.json()
    except ValueError:
        corps = {}
    detail = corps.get("detail", r.text[:200])
    if r.status_code == 422 and "erreurs" in corps:
        raise ValidationError(corps["erreurs"])
    if r.status_code == 409:
        raise IntegrityError(detail, corps.get("references"))
    if r.status_code == 404:
        raise NotFoundError(detail)
    if r.status_code == 403:
        raise ForbiddenError(detail)
    if r.status_code == 401:
        raise SmartGridError("Session expirée : reconnectez-vous.")
    raise SmartGridError(str(detail))


def _op(d: dict) -> Op:
    return Op(d["ok"], d["message"], d.get("sparql", ""), d.get("data"))


# -- lecture ------------------------------------------------------------------------------------
def rechercher(cls, texte="", filtres=None, tri=None, decroissant=False, page=1, taille=10, store=None):
    if mode() == "direct":
        return crud.rechercher(cls, texte, filtres, tri, decroissant, page, taille, store)
    params = {"q": texte, "decroissant": decroissant, "page": page, "taille": min(taille, 500)}
    if tri:
        params["tri"] = tri
    if filtres and filtres.get("type") not in (None, "", "(tous)"):
        params["filtre_type"] = filtres["type"]
    return _appel("GET", f"/api/{cls}", params=params)


def lister_ids(cls, store=None):
    if mode() == "direct":
        return crud.lister_ids(cls, store)
    lignes = rechercher(cls, taille=500)["lignes"]
    return [{"id": l["id"], "nom": l.get("hasName") or l["id"]} for l in lignes]


def fiche(identifiant, store=None):
    if mode() == "direct":
        return crud.fiche(identifiant, store)
    return _appel("GET", f"/api/Energy/{identifiant}")


def champs_formulaire(cls, store=None):
    if mode() == "direct":
        return crud.champs_formulaire(cls, store)
    return _appel("GET", f"/api/schema/formulaire/{cls}")


# -- écriture -----------------------------------------------------------------------------------
def creer(cls, donnees, identifiant=None, store=None) -> Op:
    if mode() == "direct":
        return crud.creer(cls, donnees, identifiant, store)
    return _op(_appel("POST", f"/api/{cls}", params={"id": identifiant} if identifiant else None, json=donnees))


def modifier(identifiant, donnees, store=None) -> Op:
    if mode() == "direct":
        return crud.modifier(identifiant, donnees, store)
    return _op(_appel("PUT", f"/api/Energy/{identifiant}", json=donnees))


def supprimer(identifiant, cascade=False, store=None) -> Op:
    if mode() == "direct":
        return crud.supprimer(identifiant, cascade, store)
    return _op(_appel("DELETE", f"/api/Energy/{identifiant}", params={"cascade": cascade}))


# -- langage naturel ----------------------------------------------------------------------------
def repondre(question="", confirmer=False, sparql=None, store=None, peut_ecrire=True, utilisateur=None) -> dict:
    if mode() == "direct":
        return nl2sparql.repondre(question, confirmer=confirmer, sparql=sparql, store=store,
                                  peut_ecrire=peut_ecrire, utilisateur=utilisateur)
    return _appel("POST", "/api/nl2sparql", json={"question": question, "confirm": confirmer, "sparql": sparql})
