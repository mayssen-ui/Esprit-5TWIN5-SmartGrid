"""Historique des requêtes SPARQL et favoris (fichier JSON local)."""
from __future__ import annotations

import datetime as dt
import json
import threading

from app.config import settings

_verrou = threading.Lock()


def _fichier():
    return settings.data_dir / "history.json"


def _lire() -> dict:
    f = _fichier()
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"historique": [], "favoris": []}


def _ecrire(donnees: dict) -> None:
    _fichier().write_text(json.dumps(donnees, ensure_ascii=False, indent=1), encoding="utf-8")


def ajouter_historique(requete: str, libelle: str = "", nb_resultats: int | None = None, erreur: str | None = None) -> None:
    with _verrou:
        d = _lire()
        d["historique"].append({
            "date": dt.datetime.now().isoformat(timespec="seconds"), "libelle": libelle, "requete": requete,
            "nb_resultats": nb_resultats, "erreur": erreur,
        })
        d["historique"] = d["historique"][-200:]
        _ecrire(d)


def historique(limite: int = 50) -> list[dict]:
    return list(reversed(_lire()["historique"]))[:limite]


def vider_historique() -> None:
    with _verrou:
        d = _lire()
        d["historique"] = []
        _ecrire(d)


def ajouter_favori(nom: str, requete: str) -> None:
    with _verrou:
        d = _lire()
        d["favoris"] = [f for f in d["favoris"] if f["nom"] != nom] + [{"nom": nom, "requete": requete}]
        _ecrire(d)


def favoris() -> list[dict]:
    return _lire()["favoris"]


def supprimer_favori(nom: str) -> None:
    with _verrou:
        d = _lire()
        d["favoris"] = [f for f in d["favoris"] if f["nom"] != nom]
        _ecrire(d)
