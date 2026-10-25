"""Préfixes SPARQL standards et utilitaires de formatage des termes RDF."""
from __future__ import annotations

import re

from app.config import NS

PREFIX_MAP = {
    "sg": NS,
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
    "owl": "http://www.w3.org/2002/07/owl#",
    "xsd": "http://www.w3.org/2001/XMLSchema#",
}

PREFIXES = "".join(f"PREFIX {p}: <{u}>\n" for p, u in PREFIX_MAP.items())


def decouper_operations(requete: str) -> list[str]:
    """Découpe une requête de mise à jour en opérations séparées par « ; » (hors accolades,
    chaînes de caractères et commentaires)."""
    morceaux: list[str] = []
    courant: list[str] = []
    profondeur, i, n = 0, 0, len(requete)
    while i < n:
        c = requete[i]
        if c in "\"'":
            fin = c * 3 if requete.startswith(c * 3, i) else c
            j = i + len(fin)
            while j < n and not requete.startswith(fin, j):
                j += 2 if requete[j] == "\\" else 1
            courant.append(requete[i:j + len(fin)])
            i = j + len(fin)
            continue
        if c == "#" and (i == 0 or requete[i - 1].isspace()):
            j = requete.find("\n", i)
            j = n if j < 0 else j
            courant.append(requete[i:j])
            i = j
            continue
        if c == "{":
            profondeur += 1
        elif c == "}":
            profondeur -= 1
        elif c == ";" and profondeur == 0:
            morceaux.append("".join(courant))
            courant = []
            i += 1
            continue
        courant.append(c)
        i += 1
    morceaux.append("".join(courant))
    return [m for m in morceaux if m.strip()]


def with_prefixes(requete: str) -> str:
    """Ajoute les préfixes manquants en tête de chaque opération (sans toucher à ceux déjà
    déclarés). rdflib ne partage pas le prologue entre les opérations d'une mise à jour."""
    resultat = []
    for morceau in decouper_operations(requete):
        manquants = [
            f"PREFIX {p}: <{u}>\n"
            for p, u in PREFIX_MAP.items()
            if not re.search(rf"PREFIX\s+{p}\s*:", morceau, re.IGNORECASE)
        ]
        resultat.append("".join(manquants) + morceau)
    return " ;\n".join(resultat)


def local_name(iri_complet: str) -> str:
    """Retourne la partie locale d'un IRI de l'ontologie (sinon l'IRI inchangé)."""
    return iri_complet[len(NS):] if iri_complet.startswith(NS) else iri_complet


def iri(nom_local: str) -> str:
    """Construit l'IRI complet d'un élément de l'ontologie."""
    return nom_local if nom_local.startswith("http") else NS + nom_local


def esc_literal(texte: str) -> str:
    """Échappe une chaîne pour l'insérer entre guillemets dans du SPARQL."""
    return (
        str(texte)
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
    )
