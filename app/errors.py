"""Exceptions métier, avec des messages rédigés en français clair."""
from __future__ import annotations


class SmartGridError(Exception):
    """Erreur de base : le message est toujours lisible par un utilisateur non technique."""


class ValidationError(SmartGridError):
    """Les valeurs saisies ne respectent pas les règles de l'ontologie."""

    def __init__(self, erreurs: list[str] | str):
        self.erreurs = [erreurs] if isinstance(erreurs, str) else list(erreurs)
        super().__init__(" ; ".join(self.erreurs))


class NotFoundError(SmartGridError):
    """L'élément demandé n'existe pas."""


class IntegrityError(SmartGridError):
    """L'opération casserait des liens existants entre individus."""

    def __init__(self, message: str, references: list[dict] | None = None):
        self.references = references or []
        super().__init__(message)


class ForbiddenError(SmartGridError):
    """L'utilisateur n'a pas le droit d'effectuer cette action."""


class QueryRejected(SmartGridError):
    """Requête SPARQL refusée par les garde-fous."""
