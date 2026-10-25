"""Garde-fous : validation syntaxique, types de requêtes autorisés, limite de résultats, journal."""
from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import dataclass
from typing import Any

from rdflib.plugins.sparql import parser
from rdflib.plugins.sparql.algebra import translateQuery, translateUpdate

from app.config import settings
from app.errors import QueryRejected
from app.sparql.prefixes import with_prefixes

LECTURES_AUTORISEES = {"SelectQuery": "select", "AskQuery": "ask", "ConstructQuery": "construct"}
ECRITURES_AUTORISEES = {"InsertData", "DeleteData", "DeleteWhere", "Modify"}


@dataclass
class Analyse:
    type: str  # "select" | "ask" | "construct" | "update"
    requete: str  # requête éventuellement complétée (LIMIT)
    limitee: bool = False


def _sans_chaines(q: str) -> str:
    q = re.sub(r'"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'', '""', q)
    return re.sub(r"(?m)(?<=\s)#.*$", "", q)


def analyser(requete: str, autoriser_ecriture: bool = True) -> Analyse:
    """Valide la syntaxe avec rdflib et classe la requête.

    Lecture libre : SELECT / ASK / CONSTRUCT seulement. Écriture : INSERT / DELETE seulement.
    Refuse SERVICE, LOAD, DROP, CLEAR, DESCRIBE, etc.
    """
    if not requete or not requete.strip():
        raise QueryRejected("La requête est vide.")
    if re.search(r"\bSERVICE\b", _sans_chaines(requete), re.IGNORECASE):
        raise QueryRejected("Les appels à des services externes (SERVICE) ne sont pas autorisés.")
    texte = with_prefixes(requete)
    erreur_lecture = None
    try:
        algebre = translateQuery(parser.parseQuery(texte))
        nom = algebre.algebra.name
        if nom not in LECTURES_AUTORISEES:
            raise QueryRejected("Seules les requêtes de lecture SELECT, ASK et CONSTRUCT sont autorisées en lecture libre.")
        return _limiter(Analyse(LECTURES_AUTORISEES[nom], requete))
    except QueryRejected:
        raise
    except Exception as exc:  # pas une requête de lecture valide : on teste la mise à jour
        erreur_lecture = exc
    try:
        mise_a_jour = translateUpdate(parser.parseUpdate(texte))
    except Exception as exc:
        raise QueryRejected(
            "La requête SPARQL n'est pas valide : " + _message(erreur_lecture or exc)) from None
    for op in mise_a_jour.algebra:
        if op.name not in ECRITURES_AUTORISEES:
            raise QueryRejected("Seuls INSERT et DELETE sont autorisés pour modifier les données (pas de DROP, CLEAR, LOAD…).")
    if not autoriser_ecriture:
        raise QueryRejected("Cette requête modifie les données ; elle n'est pas autorisée ici.")
    return Analyse("update", requete)


def _message(exc: Exception) -> str:
    m = str(exc).strip().splitlines()
    return (m[0] if m else exc.__class__.__name__)[:300]


def _limiter(a: Analyse) -> Analyse:
    """Ajoute ou plafonne la clause LIMIT d'un SELECT / CONSTRUCT."""
    if a.type == "ask":
        return a
    maxi = settings.max_results
    m = re.search(r"\bLIMIT\s+(\d+)\s*$", a.requete.strip(), re.IGNORECASE)
    if m:
        if int(m.group(1)) > maxi:
            a.requete = a.requete.strip()[:m.start(1)] + str(maxi)
            a.limitee = True
    elif not re.search(r"\bLIMIT\s+\d+", _sans_chaines(a.requete), re.IGNORECASE):
        a.requete = a.requete.rstrip() + f"\nLIMIT {maxi}"
        a.limitee = True
    return a


def journaliser(entree: dict[str, Any]) -> None:
    """Ajoute une ligne au journal des traductions (data/logs/nl2sparql.jsonl)."""
    entree = {"date": dt.datetime.now().isoformat(timespec="seconds"), **entree}
    with open(settings.logs_dir / "nl2sparql.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(entree, ensure_ascii=False, default=str) + "\n")


def lire_journal(limite: int = 50) -> list[dict]:
    chemin = settings.logs_dir / "nl2sparql.jsonl"
    if not chemin.exists():
        return []
    lignes = chemin.read_text(encoding="utf-8").splitlines()[-limite:]
    return [json.loads(l) for l in reversed(lignes) if l.strip()]
