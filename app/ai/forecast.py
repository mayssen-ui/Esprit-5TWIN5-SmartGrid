"""IA prédictive : prévision de la production solaire / éolienne (série horaire simulée ou importée en CSV).

Deux modèles : Holt-Winters saisonnier (statsmodels) et forêt aléatoire sur variables horaires (scikit-learn).
"""
from __future__ import annotations

import hashlib
import io

import numpy as np
import pandas as pd

from app.errors import ValidationError
from app.sparql.store import BaseStore, get_store

MODELES = {"holt_winters": "Lissage exponentiel saisonnier (Holt-Winters)", "foret": "Forêt aléatoire (scikit-learn)"}


def _graine(source_id: str) -> int:
    return int(hashlib.md5(source_id.encode()).hexdigest()[:8], 16)


def info_source(source_id: str, store: BaseStore | None = None) -> dict:
    store = store or get_store()
    r = store.query(f"""SELECT ?nom ?cap ?prod WHERE {{
        sg:{source_id} sg:hasName ?nom . OPTIONAL {{ sg:{source_id} sg:hasCapacity ?cap }}
        OPTIONAL {{ sg:{source_id} sg:hasPowerOutput ?prod }} }}""").rows
    if not r:
        raise ValidationError(f"La source « {source_id} » est introuvable.")
    r = r[0]
    if store.query(f"ASK {{ sg:{source_id} a/rdfs:subClassOf* sg:WindSource }}").boolean:
        type_ = "eolien"
    elif store.query(f"ASK {{ sg:{source_id} a/rdfs:subClassOf* sg:SolarSource }}").boolean:
        type_ = "solaire"
    else:
        type_ = "autre"
    return {"id": source_id, "nom": r["nom"], "capacite": float(r["cap"] or 0), "production": float(r["prod"] or 0), "type": type_}


def serie_simulee(source_id: str, jours: int = 21, anomalies: bool = False, store: BaseStore | None = None) -> pd.DataFrame:
    """Série horaire plausible : cloche journalière nuageuse (solaire) ou vent persistant (éolien).

    Le niveau est calé sur la capacité de la source ; la graine dépend de l'identifiant (résultat reproductible).
    """
    s = info_source(source_id, store)
    rng = np.random.default_rng(_graine(source_id))
    n = jours * 24
    idx = pd.date_range(end=pd.Timestamp.now().floor("h"), periods=n, freq="h")
    h = idx.hour.values
    cap = s["capacite"] or max(s["production"], 1.0)
    if s["type"] == "solaire":
        base = np.clip(np.sin(np.pi * (h - 6) / 12), 0, None)
        nuages = np.clip(1 - 0.5 * np.abs(rng.normal(0, 0.5, jours)).repeat(24), 0.2, 1)
        valeurs = cap * 0.9 * base * nuages * (1 + rng.normal(0, 0.03, n))
    else:
        vent = np.zeros(n)
        vent[0] = 0.5
        for i in range(1, n):
            vent[i] = 0.92 * vent[i - 1] + 0.08 * 0.5 + rng.normal(0, 0.05)
        valeurs = cap * np.clip(vent + 0.08 * np.sin(2 * np.pi * (h - 14) / 24), 0.02, 1) * 0.85
    valeurs = np.clip(valeurs, 0, cap)
    if anomalies:
        for i in rng.choice(np.arange(48, n - 5), size=4, replace=False):
            valeurs[i] = 0.0 if valeurs[i] > 0.3 * cap else cap * rng.uniform(0.9, 1.1)
    return pd.DataFrame({"horodatage": idx, "valeur": np.round(valeurs, 3)})


def lire_csv(contenu: bytes) -> pd.DataFrame:
    """CSV avec deux colonnes : date/heure et valeur (noms libres, séparateur « ; » ou « , »)."""
    try:
        df = pd.read_csv(io.BytesIO(contenu), sep=None, engine="python")
    except Exception:
        raise ValidationError("Le fichier CSV n'a pas pu être lu.") from None
    if df.shape[1] < 2:
        raise ValidationError("Le CSV doit contenir au moins deux colonnes : la date/heure puis la valeur.")
    df = df.iloc[:, :2].copy()
    df.columns = ["horodatage", "valeur"]
    df["horodatage"] = pd.to_datetime(df["horodatage"], errors="coerce")
    df["valeur"] = pd.to_numeric(df["valeur"].astype(str).str.replace(",", "."), errors="coerce")
    df = df.dropna().sort_values("horodatage")
    if len(df) < 72:
        raise ValidationError("Il faut au moins 72 mesures horaires (3 jours) pour établir une prévision.")
    return df.set_index("horodatage").resample("h").mean().interpolate().reset_index()


def _holt_winters(y: pd.Series, horizon: int) -> np.ndarray:
    from statsmodels.tsa.holtwinters import ExponentialSmoothing

    modele = ExponentialSmoothing(y.values, trend=None, seasonal="add", seasonal_periods=24,
                                  initialization_method="estimated").fit()
    return np.asarray(modele.forecast(horizon))


def _variables(idx: pd.DatetimeIndex, l1: float, l24: float) -> list[float]:
    h = idx.hour
    return [np.sin(2 * np.pi * h / 24), np.cos(2 * np.pi * h / 24), idx.day_of_week, l1, l24]


def _foret(y: pd.Series, horizon: int) -> np.ndarray:
    from sklearn.ensemble import RandomForestRegressor

    v = y.values
    X, cible = [], []
    for i in range(24, len(v)):
        X.append(_variables(y.index[i], v[i - 1], v[i - 24]))
        cible.append(v[i])
    modele = RandomForestRegressor(n_estimators=150, random_state=0, min_samples_leaf=2).fit(np.array(X), np.array(cible))
    hist = list(v)
    pas = pd.date_range(y.index[-1] + pd.Timedelta(hours=1), periods=horizon, freq="h")
    prev = []
    for t in pas:
        x = np.array([_variables(t, hist[-1], hist[-24])])
        p = float(modele.predict(x)[0])
        hist.append(p)
        prev.append(p)
    return np.array(prev)


def prevoir(serie: pd.DataFrame, horizon: int = 48, modele: str = "holt_winters", capacite: float | None = None) -> dict:
    """Prévision à `horizon` heures. Retourne l'historique, la prévision (avec bande de confiance) et l'erreur MAE
    mesurée sur les 24 dernières heures (modèle réentraîné sans elles)."""
    if modele not in MODELES:
        raise ValidationError(f"Modèle inconnu : {modele}.")
    if len(serie) < 72:
        raise ValidationError("Il faut au moins 72 mesures horaires pour établir une prévision.")
    y = serie.set_index("horodatage")["valeur"].astype(float)
    f = _holt_winters if modele == "holt_winters" else _foret
    test = f(y.iloc[:-24], 24)
    mae = float(np.mean(np.abs(test - y.iloc[-24:].values)))
    prevision = f(y, horizon)
    haut_borne = capacite if capacite else max(float(y.max()) * 1.2, 1.0)
    prevision = np.clip(prevision, 0, haut_borne)
    marge = 1.96 * float(np.std(test - y.iloc[-24:].values)) if mae else 0.0
    idx = pd.date_range(y.index[-1] + pd.Timedelta(hours=1), periods=horizon, freq="h")
    df = pd.DataFrame({"horodatage": idx, "prevision": np.round(prevision, 3),
                       "bas": np.round(np.clip(prevision - marge, 0, None), 3),
                       "haut": np.round(np.clip(prevision + marge, 0, haut_borne), 3)})
    return {"historique": serie, "prevision": df, "mae": round(mae, 3), "modele": MODELES[modele],
            "energie_prevue": round(float(prevision.sum()), 2)}
