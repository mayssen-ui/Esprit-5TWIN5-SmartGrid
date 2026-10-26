"""Assistant SmartGrid : conversation en langage naturel, réponses fondées sur le graphe (RAG).

Principe : (1) retrouver les faits pertinents par SPARQL (règles de traduction, sinon recherche des
individus cités), (2) formuler la réponse (phrases générées à partir des résultats), (3) citer les
individus utilisés.
"""
from __future__ import annotations

from typing import Any

from app.ai import nl2sparql
from app.ai.vocab import individus_connus, normaliser
from app.labels import libelle_prop
from app.services import crud, stats
from app.sparql.store import BaseStore, get_store


def _faits_depuis_resultat(res: dict) -> list[str]:
    lignes = []
    for r in res["rows"][:30]:
        lignes.append("; ".join(f"{k} = {v}" for k, v in r.items() if v is not None))
    return lignes


def _faits_individu(identifiant: str, store: BaseStore) -> list[str]:
    f = crud.fiche(identifiant, store)
    lignes = [f"« {f['nom']} » est de type {f['type']} (identifiant {identifiant})."]
    for p, v in f["donnees"].items():
        lignes.append(f"{libelle_prop(p)} de « {f['nom']} » : {v}")
    for p, vs in f["relations"].items():
        lignes.append(f"{libelle_prop(p)} de « {f['nom']} » : " + ", ".join(f"« {x['nom']} »" for x in vs))
    for r in f["references"]:
        lignes.append(f"« {r['nom']} » est lié à « {f['nom']} » par « {libelle_prop(r['propriete'])} ».")
    return lignes


def _citations(texte_faits: str, store: BaseStore) -> list[dict]:
    """Individus du graphe dont le nom ou l'identifiant apparaît dans les faits utilisés."""
    norm = normaliser(texte_faits)
    cites = []
    for ind in individus_connus(store):
        if normaliser(ind.nom) in norm or normaliser(ind.id) in norm:
            cites.append({"id": ind.id, "nom": ind.nom, "type": ind.classe})
    return cites


def repondre(question: str, historique: list[dict] | None = None, store: BaseStore | None = None) -> dict[str, Any]:
    """Retourne {texte, sources, sparql, faits}. Ne modifie jamais les données."""
    store = store or get_store()
    faits: list[str] = []
    sparql = ""
    t = nl2sparql.traduire(question, store)
    reponse_directe = ""
    if t.sparql and not t.ecriture and not t.erreur:
        sortie = nl2sparql.repondre(question, store=store, peut_ecrire=False)
        if sortie["execute"] and sortie["resultat"]:
            sparql = sortie["sparql"]
            faits += _faits_depuis_resultat(sortie["resultat"])
            reponse_directe = sortie["message"]
    elif t.ecriture:
        return {"texte": "Je réponds seulement aux questions : pour ajouter, modifier ou supprimer un élément, "
                         "utilisez les pages de gestion ou « Poser une question » (avec confirmation).",
                "sources": [], "sparql": "", "faits": []}
    if not faits:
        individus = individus_connus(store)
        trouve = nl2sparql.trouver_individu(question, individus)
        if trouve:
            faits += _faits_individu(trouve.id, store)
            sparql = f"SELECT ?propriete ?valeur WHERE {{ sg:{trouve.id} ?propriete ?valeur }}"
            reponse_directe = f"Voici ce que je sais sur « {trouve.nom} »."
    if not faits:
        k = stats.indicateurs(store)
        faits = [f"{nom} : {val}" for nom, val in k.items()]
        reponse_directe = "Je n'ai pas trouvé d'élément précis ; voici un résumé du réseau."
    contexte = "\n".join(faits)
    texte = reponse_directe
    if len(faits) > 1 and faits[0] not in texte:
        texte += "\n\n" + "\n".join(f"- {f}" for f in faits[:10]) + ("\n- …" if len(faits) > 10 else "")
    if not texte:
        texte = "Voici les informations trouvées dans le graphe."
    cites = _citations(contexte + "\n" + texte, store)
    return {"texte": texte, "sources": cites, "sparql": sparql, "faits": faits[:30]}
