"""Routes REST de l'API SmartGrid (documentation Swagger sur /docs)."""
from __future__ import annotations

from typing import Any

import pandas as pd
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, Field

from app.ai import anomalies, chatbot, forecast, guardrails, nl2sparql, recommend, simulation
from app.api.deps import administrateur, utilisateur_courant
from app.errors import QueryRejected
from app.services import auth, complex_ops, crud, history, io_service, reasoning, stats
from app.sparql import queries as catalogue
from app.sparql.schema import get_schema, schema_en_json, schema_en_texte
from app.sparql.store import get_store

# --------------------------------------------------------------------------------------------
# Modèles de requêtes
# --------------------------------------------------------------------------------------------
class NL2SparqlIn(BaseModel):
    question: str = Field("", description="Phrase en français ou en anglais", examples=["Citer les différents bâtiments"])
    confirm: bool = Field(False, description="Doit être vrai pour exécuter un INSERT / DELETE généré")
    sparql: str | None = Field(None, description="Requête corrigée à la main (remplace la traduction)")


class SparqlIn(BaseModel):
    requete: str


class BatimentComplet(BaseModel):
    classe: str = Field("CommercialBuilding", examples=["CommercialBuilding"])
    donnees: dict[str, Any] = Field(examples=[{"hasName": "Nouveau magasin", "hasConsumption": 1.5}])
    source: str | None = Field(None, examples=["SolarFarm_Tunis"])
    noeud: str | None = Field(None, examples=["GridNode_Tunis_01"])
    batterie: str | None = None


class Reaffectation(BaseModel):
    batiment: str
    nouvelle_source: str


class AffectationUtilisateur(BaseModel):
    utilisateur: str
    batiments: list[str]
    remplacer: bool = False


class ChatIn(BaseModel):
    question: str
    historique: list[dict] = []


class SimulationIn(BaseModel):
    scenario: dict[str, Any] = Field(examples=[{"type": "panne_source", "source": "SolarFarm_Ariana", "reaffecter": True}])


def _df(df: pd.DataFrame) -> list[dict]:
    return df.where(pd.notnull(df), None).to_dict(orient="records")


# --------------------------------------------------------------------------------------------
# Authentification et schéma
# --------------------------------------------------------------------------------------------
auth_router = APIRouter(prefix="/api/auth", tags=["Authentification"])


@auth_router.post("/login", summary="Se connecter (e-mail d'un utilisateur de l'ontologie + mot de passe du rôle)")
def login(form: OAuth2PasswordRequestForm = Depends()):
    user = auth.authentifier(form.username, form.password)
    if not user:
        raise HTTPException(401, "E-mail ou mot de passe incorrect.")
    return {"access_token": auth.creer_jeton(user), "token_type": "bearer", "utilisateur": user}


@auth_router.get("/moi", summary="Qui suis-je ?")
def moi(user: dict = Depends(utilisateur_courant)):
    return user


schema_router = APIRouter(prefix="/api/schema", tags=["Schéma de l'ontologie"], dependencies=[Depends(utilisateur_courant)])


@schema_router.get("", summary="Classes, hiérarchie et propriétés (JSON)")
def schema_json():
    return schema_en_json()


@schema_router.get("/resume", summary="Résumé du schéma en texte (utilisé par l'IA)")
def schema_texte():
    return Response(schema_en_texte(), media_type="text/plain; charset=utf-8")


@schema_router.get("/formulaire/{classe}", summary="Champs du formulaire de création d'une classe")
def formulaire(classe: str):
    return crud.champs_formulaire(crud.resoudre_classe(classe))


# --------------------------------------------------------------------------------------------
# Langage humain -> SPARQL
# --------------------------------------------------------------------------------------------
nl_router = APIRouter(prefix="/api", tags=["Langage humain → SPARQL"])


@nl_router.post("/nl2sparql", summary="Traduire une phrase en SPARQL, l'exécuter et l'expliquer")
def nl2sparql_route(corps: NL2SparqlIn, user: dict = Depends(utilisateur_courant)):
    sortie = nl2sparql.repondre(
        corps.question, confirmer=corps.confirm, sparql=corps.sparql, peut_ecrire=user.get("role") == "admin",
        utilisateur=user.get("email"))
    history.ajouter_historique(sortie["sparql"], corps.question,
                               len(sortie["resultat"]["rows"]) if sortie["resultat"] else None, sortie["erreur"])
    return sortie


@nl_router.get("/nl2sparql/journal", summary="Journal des traductions", dependencies=[Depends(administrateur)])
def journal(limite: int = 50):
    return guardrails.lire_journal(limite)


sparql_router = APIRouter(prefix="/api/sparql", tags=["Éditeur SPARQL libre"])


@sparql_router.post("/query", summary="Exécuter un SELECT / ASK / CONSTRUCT")
def sparql_query(corps: SparqlIn, user: dict = Depends(utilisateur_courant)):
    try:
        analyse = guardrails.analyser(corps.requete, autoriser_ecriture=False)
    except QueryRejected as exc:
        raise HTTPException(400, str(exc))
    res = get_store().query(analyse.requete)
    res.rows = res.rows[:guardrails.settings.max_results]
    history.ajouter_historique(analyse.requete, "Éditeur SPARQL", len(res.rows))
    return {**res.to_dict(), "tronque": analyse.limitee, "sparql": analyse.requete}


@sparql_router.post("/update", summary="Exécuter un INSERT / DELETE (administrateur)")
def sparql_update(corps: SparqlIn, user: dict = Depends(administrateur)):
    try:
        guardrails.analyser(corps.requete)
    except QueryRejected as exc:
        raise HTTPException(400, str(exc))
    get_store().update(corps.requete)
    return {"ok": True, "message": "La modification a été enregistrée."}


# --------------------------------------------------------------------------------------------
# Requêtes croisées et CRUD complexe
# --------------------------------------------------------------------------------------------
croise_router = APIRouter(prefix="/api/requetes", tags=["Requêtes croisées"], dependencies=[Depends(utilisateur_courant)])


@croise_router.get("", summary="Catalogue des requêtes croisées")
def liste_requetes():
    return [{"id": q.id, "libelle": q.libelle, "explication": q.explication, "techniques": q.techniques} for q in catalogue.CATALOGUE]


@croise_router.get("/{requete_id}", summary="Exécuter une requête croisée")
def executer_requete(requete_id: str):
    q = catalogue.PAR_ID.get(requete_id)
    if not q:
        raise HTTPException(404, "Cette requête n'existe pas.")
    res = get_store().query(q.sparql)
    return {"libelle": q.libelle, "sparql": q.sparql, **res.to_dict()}


ops_router = APIRouter(prefix="/api/operations", tags=["CRUD complexe"], dependencies=[Depends(administrateur)])


@ops_router.post("/batiment-complet", summary="Créer un bâtiment et le lier à une source et à un nœud (transaction)")
def batiment_complet(c: BatimentComplet):
    return complex_ops.creer_batiment_lie(c.classe, c.donnees, c.source, c.noeud, c.batterie).to_dict()


@ops_router.post("/reaffecter", summary="Réaffecter un bâtiment à une autre source")
def reaffecter(c: Reaffectation):
    return complex_ops.reaffecter_batiment(c.batiment, c.nouvelle_source).to_dict()


@ops_router.delete("/source/{source_id}", summary="Supprimer une source en détachant ses bâtiments")
def supprimer_source(source_id: str):
    return complex_ops.supprimer_source_detachee(source_id).to_dict()


@ops_router.post("/affecter-utilisateur", summary="Affecter un utilisateur à plusieurs bâtiments")
def affecter(c: AffectationUtilisateur):
    return complex_ops.affecter_utilisateur(c.utilisateur, c.batiments, c.remplacer).to_dict()


# --------------------------------------------------------------------------------------------
# Statistiques, raisonnement, IA, import/export
# --------------------------------------------------------------------------------------------
stats_router = APIRouter(prefix="/api/stats", tags=["Statistiques"], dependencies=[Depends(utilisateur_courant)])


@stats_router.get("", summary="Indicateurs clés et toutes les statistiques")
def toutes_les_stats():
    return {"kpi": stats.indicateurs(), "tableaux": {k: _df(v) for k, v in stats.tout_calculer().items()},
            "libelles": {k: v.libelle for k, v in stats.STATS.items()}}


@stats_router.get("/export.csv", summary="Export CSV")
def export_csv():
    return Response(stats.export_csv(stats.indicateurs(), stats.tout_calculer()), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": "attachment; filename=statistiques_smartgrid.csv"})


@stats_router.get("/export.pdf", summary="Export PDF")
def export_pdf():
    return Response(stats.export_pdf(stats.indicateurs(), stats.tout_calculer()), media_type="application/pdf",
                    headers={"Content-Disposition": "attachment; filename=rapport_smartgrid.pdf"})


raison_router = APIRouter(prefix="/api/raisonnement", tags=["Raisonnement"], dependencies=[Depends(utilisateur_courant)])


@raison_router.post("", summary="Lancer le raisonneur HermiT et vérifier la cohérence")
def raisonner():
    return reasoning.verifier_coherence()


ia_router = APIRouter(prefix="/api/ia", tags=["IA et recommandations"], dependencies=[Depends(utilisateur_courant)])


@ia_router.get("/recommandations/{batiment}", summary="Meilleures sources pour un bâtiment")
def recommandations(batiment: str):
    return _df(recommend.recommander(batiment))


@ia_router.get("/surcharges", summary="Sources surchargées")
def surcharges():
    d = recommend.sources_surchargees()
    return _df(d.replace([float("inf")], None))


@ia_router.get("/anomalies", summary="Alertes sur l'état du réseau")
def alertes():
    return anomalies.anomalies_reseau()


@ia_router.get("/prevision/{source}", summary="Prévision de production d'une source")
def prevision(source: str, horizon: int = Query(48, ge=6, le=168), modele: str = "holt_winters"):
    info = forecast.info_source(source)
    r = forecast.prevoir(forecast.serie_simulee(source), horizon, modele, info["capacite"] or None)
    return {"source": info, "mae": r["mae"], "modele": r["modele"], "energie_prevue": r["energie_prevue"],
            "prevision": _df(r["prevision"].assign(horodatage=lambda d: d["horodatage"].astype(str)))}


@ia_router.post("/simulation", summary="Simulation « et si »")
def simulation_route(c: SimulationIn):
    r = simulation.simuler(c.scenario)
    for k in ("avant", "apres"):
        r[k]["details_sources"] = _df(r[k]["details_sources"].replace([float("inf")], None))
    return r


@ia_router.post("/chat", summary="Assistant SmartGrid (réponses fondées sur le graphe)")
def chat(c: ChatIn):
    return chatbot.repondre(c.question, c.historique)


io_router = APIRouter(prefix="/api", tags=["Import / export"])


@io_router.get("/export/{format}", summary="Exporter toute l'ontologie (rdfxml, turtle, jsonld, ntriples)",
               dependencies=[Depends(utilisateur_courant)])
def export_graphe(format: str):
    contenu, mime, ext = io_service.exporter_graphe(format)
    return Response(contenu, media_type=mime, headers={"Content-Disposition": f"attachment; filename=smartgrid{ext}"})


@io_router.get("/export-csv/{classe}", summary="Exporter une classe en CSV", dependencies=[Depends(utilisateur_courant)])
def export_csv_classe(classe: str):
    return Response(io_service.exporter_csv(crud.resoudre_classe(classe)), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f"attachment; filename={classe}.csv"})


@io_router.post("/import/rdf", summary="Importer un fichier RDF", dependencies=[Depends(administrateur)])
async def import_rdf(format: str = Form("rdfxml"), fichier: UploadFile = File(...)):
    return io_service.importer_rdf(await fichier.read(), format)


@io_router.post("/import/csv", summary="Importer des individus en masse depuis un CSV", dependencies=[Depends(administrateur)])
async def import_csv(classe: str | None = Form(None), tout_ou_rien: bool = Form(True), fichier: UploadFile = File(...)):
    return io_service.importer_csv(await fichier.read(), classe, tout_ou_rien=tout_ou_rien)


# --------------------------------------------------------------------------------------------
# CRUD générique /api/{classe}  (déclaré en dernier : les routes fixes passent avant)
# --------------------------------------------------------------------------------------------
crud_router = APIRouter(prefix="/api", tags=["CRUD des individus"])


@crud_router.get("/{classe}", summary="Lister les individus d'une classe (recherche, tri, pagination)",
                 dependencies=[Depends(utilisateur_courant)])
def lister(classe: str, q: str = "", tri: str | None = None, decroissant: bool = False,
           page: int = Query(1, ge=1), taille: int = Query(20, ge=1, le=500), filtre_type: str | None = None):
    return crud.rechercher(crud.resoudre_classe(classe), q, {"type": filtre_type} if filtre_type else None,
                           tri, decroissant, page, taille)


@crud_router.get("/{classe}/{identifiant}", summary="Fiche détail d'un individu", dependencies=[Depends(utilisateur_courant)])
def detail(classe: str, identifiant: str):
    crud.resoudre_classe(classe)
    return crud.fiche(identifiant)


@crud_router.post("/{classe}", status_code=201, summary="Créer un individu", dependencies=[Depends(administrateur)])
def creer(classe: str, donnees: dict[str, Any], id: str | None = None):
    return crud.creer(classe, donnees, id).to_dict()


@crud_router.put("/{classe}/{identifiant}", summary="Modifier un individu", dependencies=[Depends(administrateur)])
def modifier(classe: str, identifiant: str, donnees: dict[str, Any]):
    crud.resoudre_classe(classe)
    return crud.modifier(identifiant, donnees).to_dict()


@crud_router.delete("/{classe}/{identifiant}", summary="Supprimer un individu (cascade=true pour rompre les liens)",
                    dependencies=[Depends(administrateur)])
def supprimer(classe: str, identifiant: str, cascade: bool = False):
    crud.resoudre_classe(classe)
    return crud.supprimer(identifiant, cascade).to_dict()


ROUTEURS = [auth_router, schema_router, nl_router, sparql_router, croise_router, ops_router, stats_router,
            raison_router, ia_router, io_router, crud_router]
