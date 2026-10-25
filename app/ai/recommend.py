"""Recommandations : meilleure source pour un bâtiment non alimenté, et sources surchargées."""
from __future__ import annotations

from collections import deque

import pandas as pd

from app.sparql.store import BaseStore, get_store


def _sources(store: BaseStore) -> pd.DataFrame:
    """Sources avec capacité, production, énergie renouvelable ?, et consommation déjà servie."""
    rows = store.query("""SELECT ?source ?nom ?capacite ?production (COALESCE(?servie, 0) AS ?consommation_servie)
        WHERE {
          ?source a/rdfs:subClassOf* sg:EnergySource ; a owl:NamedIndividual ; sg:hasName ?nom .
          OPTIONAL { ?source sg:hasCapacity ?capacite }
          OPTIONAL { ?source sg:hasPowerOutput ?production }
          OPTIONAL { SELECT ?source (SUM(?c) AS ?servie)
                     WHERE { ?b sg:suppliedBy ?source ; sg:hasConsumption ?c } GROUP BY ?source }
        } ORDER BY ?nom""").rows
    renouvelables = {r["s"] for r in store.query(
        "SELECT DISTINCT ?s WHERE { ?s sg:produces ?e . ?e a/rdfs:subClassOf* sg:RenewableEnergy }").rows}
    df = pd.DataFrame(rows, columns=["source", "nom", "capacite", "production", "consommation_servie"])
    for c in ("capacite", "production", "consommation_servie"):
        df[c] = pd.to_numeric(df[c]).fillna(0.0)
    df["renouvelable"] = df["source"].isin(renouvelables).astype(int)
    return df


def _noeuds_des_sources(store: BaseStore) -> dict[str, set[str]]:
    res: dict[str, set[str]] = {}
    for r in store.query("""SELECT ?s ?n WHERE { { ?n sg:hasSource ?s } UNION { ?s sg:feeds ?n } }""").rows:
        res.setdefault(r["s"], set()).add(r["n"])
    return res


def _distances(store: BaseStore, depart: str) -> dict[str, int]:
    """Nombre de liaisons « connecté à » entre `depart` et chaque nœud (parcours en largeur)."""
    voisins: dict[str, set[str]] = {}
    for r in store.query("SELECT ?a ?b WHERE { ?a sg:connectedTo ?b }").rows:
        voisins.setdefault(r["a"], set()).add(r["b"])
        voisins.setdefault(r["b"], set()).add(r["a"])
    dist, file = {depart: 0}, deque([depart])
    while file:
        n = file.popleft()
        for v in voisins.get(n, ()):
            if v not in dist:
                dist[v] = dist[n] + 1
                file.append(v)
    return dist


def batiments_sans_alimentation(store: BaseStore | None = None) -> pd.DataFrame:
    store = store or get_store()
    rows = store.query("""SELECT ?batiment ?nom ?consommation ?noeud WHERE {
      ?batiment a/rdfs:subClassOf* sg:Building ; a owl:NamedIndividual ; sg:hasName ?nom .
      OPTIONAL { ?batiment sg:hasConsumption ?consommation }
      OPTIONAL { ?batiment sg:locatedIn ?noeud }
      FILTER NOT EXISTS { ?batiment sg:suppliedBy ?s }
    } ORDER BY ?nom""").rows
    df = pd.DataFrame(rows, columns=["batiment", "nom", "consommation", "noeud"])
    df["consommation"] = pd.to_numeric(df["consommation"]).fillna(0.0)
    return df


def recommander(batiment: str, store: BaseStore | None = None) -> pd.DataFrame:
    """Classe les sources candidates pour un bâtiment (score sur 100).

    Critères : capacité restante (40 %), proximité du nœud (35 %), énergie renouvelable (25 %).
    """
    store = store or get_store()
    info = store.query(f"""SELECT ?nom ?c ?n WHERE {{ sg:{batiment} sg:hasName ?nom .
      OPTIONAL {{ sg:{batiment} sg:hasConsumption ?c }} OPTIONAL {{ sg:{batiment} sg:locatedIn ?n }} }}""").rows
    conso = float(info[0]["c"] or 0) if info else 0.0
    noeud = info[0]["n"] if info else None
    sources = _sources(store)
    noeuds_src = _noeuds_des_sources(store)
    dist = _distances(store, noeud) if noeud else {}
    lignes = []
    for _, s in sources.iterrows():
        restante = s["production"] - s["consommation_servie"]
        score_cap = max(0.0, min(1.0, restante / max(conso * 2, 1e-9))) if restante >= conso else 0.0
        d = min((dist[n] for n in noeuds_src.get(s["source"], ()) if n in dist), default=None)
        prox = {0: 1.0, 1: 0.6, 2: 0.3}.get(d, 0.1)
        score = 100 * (0.40 * score_cap + 0.35 * prox + 0.25 * float(s["renouvelable"]))
        raisons = []
        raisons.append("assez de puissance disponible" if restante >= conso else "puissance disponible insuffisante")
        raisons.append({0: "sur le même nœud", 1: "sur un nœud voisin", 2: "à 2 nœuds"}.get(d, "éloignée du bâtiment"))
        raisons.append("énergie renouvelable" if s["renouvelable"] else "énergie non renouvelable")
        lignes.append({
            "source": s["source"], "nom": s["nom"], "score": round(score, 1), "puissance_disponible": round(restante, 3),
            "capacite_installee": s["capacite"], "renouvelable": bool(s["renouvelable"]),
            "distance_noeuds": d, "raison": ", ".join(raisons),
            "compatible": restante >= conso,
        })
    return pd.DataFrame(lignes).sort_values("score", ascending=False).reset_index(drop=True)


def sources_surchargees(store: BaseStore | None = None, seuil_alerte: float = 0.8) -> pd.DataFrame:
    """Charge = consommation servie / puissance produite. > 100 % : surchargée ; ≥ 80 % : à surveiller."""
    store = store or get_store()
    df = _sources(store)
    df = df[df["consommation_servie"] > 0].copy()
    if df.empty:
        return pd.DataFrame(columns=["source", "nom", "production", "consommation_servie", "charge", "statut"])
    df["charge"] = df.apply(lambda r: (r["consommation_servie"] / r["production"]) if r["production"] > 0 else float("inf"), axis=1)
    df["statut"] = df["charge"].apply(lambda c: "Surchargée" if c > 1 else ("À surveiller" if c >= seuil_alerte else "Normale"))
    return df[["source", "nom", "production", "consommation_servie", "charge", "statut"]].sort_values("charge", ascending=False).reset_index(drop=True)
