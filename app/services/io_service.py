"""Import / export : RDF/XML, Turtle, JSON-LD, N-Triples, CSV (avec import en masse d'individus)."""
from __future__ import annotations

import csv
import io
from typing import Any

from rdflib import Graph

from app.errors import SmartGridError, ValidationError
from app.services import crud
from app.sparql.schema import get_schema
from app.sparql.store import BaseStore, get_store

FORMATS = {
    "rdfxml": ("xml", "application/rdf+xml", ".owl", "RDF/XML (Protégé)"),
    "turtle": ("turtle", "text/turtle", ".ttl", "Turtle"),
    "jsonld": ("json-ld", "application/ld+json", ".jsonld", "JSON-LD"),
    "ntriples": ("nt", "application/n-triples", ".nt", "N-Triples"),
}


def exporter_graphe(fmt: str, store: BaseStore | None = None) -> tuple[bytes, str, str]:
    """Retourne (contenu, type MIME, extension) du graphe complet."""
    if fmt not in FORMATS:
        raise ValidationError(f"Format inconnu « {fmt} ». Formats possibles : {', '.join(FORMATS)}.")
    store = store or get_store()
    rdflib_fmt, mime, ext, _ = FORMATS[fmt]
    g = store.snapshot()
    contenu = g.serialize(format=rdflib_fmt)
    return (contenu if isinstance(contenu, bytes) else contenu.encode("utf-8")), mime, ext


def exporter_csv(cls: str, store: BaseStore | None = None) -> bytes:
    """Tableau CSV (séparateur « ; », UTF-8 avec BOM pour Excel) de tous les individus d'une classe."""
    donnees = crud.rechercher(cls, taille=100000, store=store)
    sortie = io.StringIO()
    w = csv.DictWriter(sortie, fieldnames=donnees["colonnes"], delimiter=";", extrasaction="ignore")
    w.writeheader()
    for l in donnees["lignes"]:
        w.writerow({k: ("" if v is None else v) for k, v in l.items()})
    return ("﻿" + sortie.getvalue()).encode("utf-8")


def importer_rdf(contenu: bytes, fmt: str, store: BaseStore | None = None) -> dict:
    """Fusionne un fichier RDF dans le graphe (INSERT DATA), après contrôle de syntaxe."""
    store = store or get_store()
    if fmt not in FORMATS:
        raise ValidationError("Format de fichier non pris en charge.")
    g = Graph()
    try:
        g.parse(data=contenu, format=FORMATS[fmt][0])
    except Exception as exc:
        raise ValidationError(f"Le fichier n'est pas un {FORMATS[fmt][3]} valide : {str(exc)[:200]}") from None
    if len(g) == 0:
        raise ValidationError("Le fichier ne contient aucune donnée.")
    nt = g.serialize(format="nt")
    nt = nt.decode("utf-8") if isinstance(nt, bytes) else nt
    store.update("INSERT DATA {\n" + nt + "}")
    return {"triplets": len(g), "message": f"{len(g)} information(s) ont été importées."}


def importer_csv(contenu: bytes, cls: str | None, store: BaseStore | None = None, tout_ou_rien: bool = True) -> dict:
    """Import en masse d'individus depuis un CSV.

    Colonnes : `id` (facultatif), `classe` (facultatif si `cls` est fourni), puis une colonne par propriété
    (ex. hasName, hasCapacity, suppliedBy…). Plusieurs valeurs d'une relation : séparées par « | ».
    """
    store = store or get_store()
    texte = contenu.decode("utf-8-sig", errors="replace")
    sep = ";" if texte.splitlines()[0].count(";") >= texte.splitlines()[0].count(",") else ","
    lecteur = csv.DictReader(io.StringIO(texte), delimiter=sep)
    if not lecteur.fieldnames:
        raise ValidationError("Le fichier CSV est vide.")
    schema = get_schema()
    crees: list[str] = []
    erreurs: list[dict] = []

    def traiter() -> None:
        for numero, ligne in enumerate(lecteur, start=2):
            classe = (ligne.get("classe") or cls or "").strip()
            if not classe:
                erreurs.append({"ligne": numero, "message": "Aucune catégorie indiquée (colonne « classe »)."})
                continue
            donnees: dict[str, Any] = {}
            for col, val in ligne.items():
                if not col or col in ("id", "classe", "type") or val is None or str(val).strip() == "":
                    continue
                if col in schema.props and schema.props[col].type == "object":
                    donnees[col] = [v.strip() for v in str(val).replace(";", "|").replace(",", "|").split("|") if v.strip()]
                else:
                    donnees[col] = val.strip()
            try:
                op = crud.creer(classe, donnees, (ligne.get("id") or "").strip() or None, store)
                crees.append(op.data["id"])
            except SmartGridError as exc:
                erreurs.append({"ligne": numero, "message": str(exc)})

    if tout_ou_rien:
        try:
            with store.transaction():
                traiter()
                if erreurs:
                    raise ValidationError("annulation")
        except ValidationError as exc:
            if str(exc) != "annulation":
                raise
            return {"crees": 0, "erreurs": erreurs, "message": "Aucun élément n'a été importé : corrigez les lignes en erreur."}
    else:
        traiter()
    return {"crees": len(crees), "ids": crees, "erreurs": erreurs,
            "message": f"{len(crees)} élément(s) importé(s)" + (f", {len(erreurs)} ligne(s) ignorée(s)." if erreurs else ".")}
