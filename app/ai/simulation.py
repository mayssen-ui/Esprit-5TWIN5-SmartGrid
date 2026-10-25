"""Simulation « et si » : on joue un scénario sur une copie du graphe et on compare les bilans."""
from __future__ import annotations

from typing import Any

from rdflib import Graph

from app.ai import recommend
from app.errors import ValidationError
from app.services import crud, stats
from app.sparql.store import BaseStore, RdflibStore, get_store


def _copie(store: BaseStore) -> RdflibStore:
    g = Graph()
    for t in store.snapshot():
        g.add(t)
    return RdflibStore.depuis_graphe(g)


def bilan(store: BaseStore) -> dict[str, Any]:
    """Production, consommation, bilan, bâtiments sans alimentation et sources surchargées."""
    b = stats.executer("bilan_global", store).iloc[0]
    sans = recommend.batiments_sans_alimentation(store)
    surch = recommend.sources_surchargees(store)
    return {
        "production": round(float(b["production"] or 0), 3),
        "consommation": round(float(b["consommation"] or 0), 3),
        "bilan": round(float((b["production"] or 0) - (b["consommation"] or 0)), 3),
        "batiments_sans_alimentation": sans["nom"].tolist(),
        "sources_surchargees": surch[surch["statut"] == "Surchargée"]["nom"].tolist(),
        "details_sources": surch,
    }


def simuler(scenario: dict[str, Any], store: BaseStore | None = None) -> dict[str, Any]:
    """Scénarios pris en charge :

    - {"type": "ajout_batiment", "consommation": 3.5, "source": "<id>"|None, "noeud": "<id>"|None}
    - {"type": "panne_source", "source": "<id>", "reaffecter": True|False}
    """
    store = store or get_store()
    avant = bilan(store)
    sim = _copie(store)
    notes: list[str] = []
    t = scenario.get("type")

    if t == "ajout_batiment":
        conso = float(scenario.get("consommation") or 0)
        if conso <= 0:
            raise ValidationError("La consommation du bâtiment simulé doit être positive.")
        donnees: dict[str, Any] = {"hasName": "Bâtiment simulé", "hasConsumption": conso}
        if scenario.get("source"):
            donnees["suppliedBy"] = scenario["source"]
        if scenario.get("noeud"):
            donnees["locatedIn"] = scenario["noeud"]
        crud.creer(scenario.get("classe") or "CommercialBuilding", donnees, "Batiment_simule", sim)
        notes.append(f"Un bâtiment consommant {conso:g} MW est ajouté"
                     + (f" et alimenté par « {scenario['source']} »." if scenario.get("source") else " sans source."))
        if not scenario.get("source"):
            reco = recommend.recommander("Batiment_simule", sim)
            if len(reco):
                notes.append(f"Source la mieux adaptée : « {reco.iloc[0]['nom']} » (score {reco.iloc[0]['score']}).")
    elif t == "panne_source":
        src = scenario.get("source")
        if not src or not crud.existe(src, sim):
            raise ValidationError("Choisissez la source qui tombe en panne.")
        touches = [r["b"] for r in sim.query(f"SELECT ?b WHERE {{ ?b sg:suppliedBy sg:{src} }}").rows]
        sim.update(f"DELETE {{ sg:{src} sg:hasPowerOutput ?p }} INSERT {{ sg:{src} sg:hasPowerOutput 0.0 }} "
                   f"WHERE {{ OPTIONAL {{ sg:{src} sg:hasPowerOutput ?p }} }}")
        notes.append(f"La source « {src} » tombe en panne (production nulle) : {len(touches)} bâtiment(s) touché(s).")
        if scenario.get("reaffecter"):
            for b in touches:
                reco = recommend.recommander(b, sim)
                reco = reco[(reco["source"] != src) & (reco["compatible"])]
                if len(reco):
                    meilleure = reco.iloc[0]["source"]
                    sim.update(f"DELETE {{ sg:{b} sg:suppliedBy sg:{src} }} INSERT {{ sg:{b} sg:suppliedBy sg:{meilleure} }} WHERE {{}}")
                    notes.append(f"« {b} » est basculé sur « {meilleure} ».")
                else:
                    notes.append(f"« {b} » n'a aucune source de secours disponible.")
    else:
        raise ValidationError("Scénario inconnu : choisissez « ajout d'un bâtiment » ou « panne d'une source ».")

    apres = bilan(sim)
    return {"avant": avant, "apres": apres, "notes": notes,
            "ecart_bilan": round(apres["bilan"] - avant["bilan"], 3)}
