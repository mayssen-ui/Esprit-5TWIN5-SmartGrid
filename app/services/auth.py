"""Authentification simple par rôle, liée à la classe User de l'ontologie.

L'utilisateur est identifié par son adresse e-mail (sg:hasEmail) ; son rôle vient de sg:hasRole
(« admin » : tout ; « lecteur » : lecture seule). Les mots de passe sont communs à chaque rôle
et définis dans le fichier .env (aucun mot de passe n'est stocké dans l'ontologie).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

from app.config import settings
from app.errors import ForbiddenError
from app.sparql.prefixes import esc_literal
from app.sparql.store import BaseStore, get_store

DUREE_JETON = 8 * 3600


def trouver_utilisateur(email: str, store: BaseStore | None = None) -> dict | None:
    store = store or get_store()
    rows = store.query(f"""SELECT ?id ?nom ?email ?role WHERE {{
  ?id a sg:User ; sg:hasEmail ?email .
  OPTIONAL {{ ?id sg:hasName ?nom }} OPTIONAL {{ ?id sg:hasRole ?role }}
  FILTER(LCASE(STR(?email)) = "{esc_literal(email.strip().lower())}") }}""").rows
    if not rows:
        return None
    r = rows[0]
    return {"id": r["id"], "nom": r["nom"] or r["id"], "email": r["email"], "role": (r["role"] or "lecteur").lower()}


def authentifier(email: str, mot_de_passe: str, store: BaseStore | None = None) -> dict | None:
    """Retourne l'utilisateur si l'e-mail existe dans l'ontologie et le mot de passe correspond à son rôle."""
    user = trouver_utilisateur(email or "", store)
    if not user:
        return None
    attendu = settings.admin_password if user["role"] == "admin" else settings.reader_password
    return user if hmac.compare_digest(str(mot_de_passe or ""), attendu) else None


def liste_comptes(store: BaseStore | None = None) -> list[dict]:
    store = store or get_store()
    rows = store.query("SELECT ?id ?nom ?email ?role WHERE { ?id a sg:User ; sg:hasEmail ?email . "
                       "OPTIONAL { ?id sg:hasName ?nom } OPTIONAL { ?id sg:hasRole ?role } } ORDER BY ?nom").rows
    return [{"id": r["id"], "nom": r["nom"], "email": r["email"], "role": r["role"]} for r in rows]


# -- jetons signés (API) ----------------------------------------------------------------------
def _signer(corps: bytes) -> str:
    return hmac.new(settings.secret_key.encode(), corps, hashlib.sha256).hexdigest()


def creer_jeton(user: dict) -> str:
    charge = base64.urlsafe_b64encode(json.dumps({**user, "exp": time.time() + DUREE_JETON}).encode())
    return f"{charge.decode()}.{_signer(charge)}"


def verifier_jeton(jeton: str) -> dict | None:
    try:
        charge, signature = jeton.rsplit(".", 1)
        if not hmac.compare_digest(signature, _signer(charge.encode())):
            return None
        donnees = json.loads(base64.urlsafe_b64decode(charge.encode()))
        return donnees if donnees.get("exp", 0) > time.time() else None
    except Exception:
        return None


def exiger_ecriture(user: dict | None) -> None:
    """Lève ForbiddenError si l'utilisateur n'est pas administrateur."""
    if user is None or user.get("role") != "admin":
        raise ForbiddenError("Cette action est réservée aux administrateurs. Votre rôle est en lecture seule.")
