"""Application FastAPI SmartGrid.

Lancement :  uvicorn app.api.main:app --reload      (documentation Swagger : http://localhost:8000/docs)
"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.routes import ROUTEURS
from app.config import settings
from app.errors import ForbiddenError, IntegrityError, NotFoundError, QueryRejected, SmartGridError, ValidationError

DESCRIPTION = """
API REST du réseau électrique intelligent **SmartGrid** (ontologie OWL, SPARQL 1.1).

* Connectez-vous avec le bouton **Authorize** (e-mail d'un utilisateur de l'ontologie, mot de passe de son rôle).
* Rôle **admin** : lecture et écriture. Rôle **lecteur** : lecture seule.
* `POST /api/nl2sparql` traduit une phrase en français en requête SPARQL.
"""

app = FastAPI(title="SmartGrid Semantic API", version="1.0.0", description=DESCRIPTION)
for routeur in ROUTEURS:
    app.include_router(routeur)


@app.get("/", include_in_schema=False)
def accueil():
    return {"message": "API SmartGrid en marche. Documentation : /docs", "moteur": settings.backend}


def _reponse(code: int, exc: Exception, **extra) -> JSONResponse:
    return JSONResponse(status_code=code, content={"detail": str(exc), **extra})


@app.exception_handler(ValidationError)
async def _validation(_: Request, exc: ValidationError):
    return _reponse(422, exc, erreurs=exc.erreurs)


@app.exception_handler(NotFoundError)
async def _introuvable(_: Request, exc: NotFoundError):
    return _reponse(404, exc)


@app.exception_handler(IntegrityError)
async def _integrite(_: Request, exc: IntegrityError):
    return _reponse(409, exc, references=exc.references)


@app.exception_handler(ForbiddenError)
async def _interdit(_: Request, exc: ForbiddenError):
    return _reponse(403, exc)


@app.exception_handler(QueryRejected)
async def _refusee(_: Request, exc: QueryRejected):
    return _reponse(400, exc)


@app.exception_handler(SmartGridError)
async def _autre(_: Request, exc: SmartGridError):
    return _reponse(400, exc)
