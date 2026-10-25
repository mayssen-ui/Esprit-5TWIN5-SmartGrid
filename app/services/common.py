"""Types et fonctions partagés par les services."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any


@dataclass
class Op:
    """Résultat d'une opération : message lisible, requête SPARQL exécutée, données éventuelles."""

    ok: bool
    message: str
    sparql: str = ""
    data: Any = None

    def to_dict(self) -> dict:
        return {"ok": self.ok, "message": self.message, "sparql": self.sparql, "data": self.data}


def sans_accents(texte: str) -> str:
    """Minuscule et sans accents (comparaisons tolérantes, recherche, synonymes)."""
    s = unicodedata.normalize("NFD", str(texte))
    return "".join(c for c in s if unicodedata.category(c) != "Mn").lower().replace("œ", "oe").replace("’", "'")


def slug(texte: str) -> str:
    """Transforme un nom en identifiant valide (ex. « Batterie Sousse » -> « Batterie_Sousse »)."""
    s = "".join(c for c in unicodedata.normalize("NFD", str(texte)) if unicodedata.category(c) != "Mn")
    s = s.replace("œ", "oe").replace("Œ", "Oe")
    s = re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_")
    if not s:
        s = "individu"
    s = s[0].upper() + s[1:] if s[0].isalpha() else "I_" + s
    return s


ID_VALIDE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
