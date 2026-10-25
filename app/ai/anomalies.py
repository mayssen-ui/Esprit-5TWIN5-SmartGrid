"""Détection d'anomalies : séries temporelles (IsolationForest / z-score) et état instantané du réseau."""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.sparql.store import BaseStore, get_store


def detecter_serie(serie: pd.DataFrame, methode: str = "isolation", sensibilite: float = 0.02) -> pd.DataFrame:
    """Ajoute les colonnes `anomalie` (booléen) et `score` à une série {horodatage, valeur}.

    - « isolation » : IsolationForest sur (valeur, écart au profil horaire) ; `sensibilite` = part attendue d'anomalies.
    - « zscore » : écart au profil horaire moyen, anormal si |z| > 3.
    """
    df = serie.copy()
    df["heure"] = pd.to_datetime(df["horodatage"]).dt.hour
    profil = df.groupby("heure")["valeur"].transform("median")
    df["ecart"] = df["valeur"] - profil
    if methode == "zscore":
        ecart_type = df["ecart"].std() or 1.0
        df["score"] = ((df["ecart"] - df["ecart"].mean()) / ecart_type).abs()
        df["anomalie"] = df["score"] > 3
    else:
        from sklearn.ensemble import IsolationForest

        modele = IsolationForest(contamination=min(max(sensibilite, 0.001), 0.2), random_state=0)
        X = df[["valeur", "ecart"]].values
        df["anomalie"] = modele.fit_predict(X) == -1
        df["score"] = -modele.score_samples(X)
    return df.drop(columns=["heure"])


def anomalies_reseau(store: BaseStore | None = None) -> list[dict]:
    """Alertes sur l'état actuel du graphe : production/consommation atypiques, sources saturées ou à l'arrêt."""
    store = store or get_store()
    alertes: list[dict] = []

    sources = store.query("""SELECT ?s ?nom ?cap ?prod WHERE { ?s a/rdfs:subClassOf* sg:EnergySource ; a owl:NamedIndividual ;
        sg:hasName ?nom ; sg:hasCapacity ?cap ; sg:hasPowerOutput ?prod }""").rows
    for r in sources:
        taux = (r["prod"] / r["cap"]) if r["cap"] else 0
        if r["prod"] <= 0:
            alertes.append({"gravite": "critique", "element": r["s"], "nom": r["nom"],
                            "message": f"La source « {r['nom']} » ne produit rien actuellement."})
        elif taux > 0.95:
            alertes.append({"gravite": "avertissement", "element": r["s"], "nom": r["nom"],
                            "message": f"La source « {r['nom']} » fonctionne à {taux:.0%} de sa capacité : risque de saturation."})
        elif taux < 0.3:
            alertes.append({"gravite": "information", "element": r["s"], "nom": r["nom"],
                            "message": f"La source « {r['nom']} » est très peu utilisée ({taux:.0%} de sa capacité)."})

    batiments = store.query("""SELECT ?b ?nom ?c ?t WHERE { ?b a/rdfs:subClassOf* sg:Building ; a owl:NamedIndividual ;
        sg:hasName ?nom ; sg:hasConsumption ?c . ?b a ?t . FILTER(?t IN (sg:ResidentialBuilding, sg:CommercialBuilding, sg:IndustrialBuilding)) }""").rows
    df = pd.DataFrame(batiments, columns=["b", "nom", "c", "t"])
    for t, groupe in df.groupby("t"):
        if len(groupe) < 3:
            continue
        mediane = groupe["c"].median()
        mad = (groupe["c"] - mediane).abs().median() or max(mediane * 0.1, 1e-6)
        for _, r in groupe.iterrows():
            z = 0.6745 * (r["c"] - mediane) / mad
            if abs(z) > 3.5:
                alertes.append({"gravite": "avertissement", "element": r["b"], "nom": r["nom"],
                                "message": f"« {r['nom']} » consomme {'beaucoup plus' if z > 0 else 'beaucoup moins'} "
                                           f"({r['c']:g} MW) que les autres bâtiments de même type (médiane {mediane:g} MW)."})

    for r in store.query("""SELECT ?nom ?c ?sn ?p WHERE { ?b sg:hasName ?nom ; sg:hasConsumption ?c ; sg:suppliedBy ?s .
        ?s sg:hasName ?sn ; sg:hasPowerOutput ?p . FILTER(?c > ?p) }""").rows:
        alertes.append({"gravite": "critique", "element": r["nom"], "nom": r["nom"],
                        "message": f"« {r['nom']} » consomme {r['c']:g} MW, plus que la production de sa source « {r['sn']} » ({r['p']:g} MW)."})
    ordre = {"critique": 0, "avertissement": 1, "information": 2}
    return sorted(alertes, key=lambda a: ordre[a["gravite"]])
