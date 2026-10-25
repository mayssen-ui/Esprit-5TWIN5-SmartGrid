"""Dépendances FastAPI : authentification par jeton et contrôle des rôles."""
from __future__ import annotations

from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer

from app.config import settings
from app.services import auth

schema_oauth = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)

UTILISATEUR_LOCAL = {"id": "local", "nom": "Mode sans authentification", "email": "", "role": "admin"}


def utilisateur_courant(jeton: str | None = Depends(schema_oauth)) -> dict:
    """Utilisateur connecté (lecteur ou admin). Si SG_API_AUTH=false, tout le monde est administrateur."""
    if not settings.api_auth:
        return UTILISATEUR_LOCAL
    user = auth.verifier_jeton(jeton) if jeton else None
    if not user:
        raise HTTPException(401, "Connexion requise : identifiez-vous avec votre e-mail et votre mot de passe.",
                            headers={"WWW-Authenticate": "Bearer"})
    return user


def administrateur(user: dict = Depends(utilisateur_courant)) -> dict:
    """Réservé aux administrateurs : les lecteurs reçoivent une erreur 403."""
    if user.get("role") != "admin":
        raise HTTPException(403, "Cette action est réservée aux administrateurs (votre rôle est en lecture seule).")
    return user
