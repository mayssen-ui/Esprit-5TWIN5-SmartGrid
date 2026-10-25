"""IA : prévisions de production, détection d'anomalies, recommandations de sources, simulation « et si »."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app.ai import anomalies, forecast, recommend, simulation
from app.errors import SmartGridError
from app.services import complex_ops, crud
from app.sparql.store import get_store
from app.ui import common

common.exiger_connexion()
store = get_store()
st.title("📈 Prévisions, alertes et simulation")

onglets = st.tabs(["🔮 Prévision", "🚨 Anomalies", "💡 Recommandations", "🧪 Simulation « et si »"])
sources = [i for i in crud.lister_ids("EnergySource", store)]
noms_sources = {s["id"]: s["nom"] for s in sources}
VERT, ORANGE, ROUGE = "#1f6f5c", "#e0a030", "#c4553d"

# ------------------------------------------------------------------------------------ prévision
with onglets[0]:
    common.phrase("Prévoir la production d'une source pour les prochaines heures, à partir d'une série horaire simulée ou de votre fichier CSV.")
    c1, c2, c3 = st.columns(3)
    src = c1.selectbox("Source", list(noms_sources), format_func=lambda i: noms_sources[i], key="prev_src")
    horizon = c2.slider("Horizon (heures)", 12, 168, 48, 12)
    modele = c3.selectbox("Méthode", list(forecast.MODELES), format_func=forecast.MODELES.get)
    fichier = st.file_uploader("Ou importez vos mesures (CSV : date/heure ; valeur)", type=["csv"])
    try:
        info = forecast.info_source(src, store)
        serie = forecast.lire_csv(fichier.getvalue()) if fichier else forecast.serie_simulee(src, store=store)
        st.caption("Données : " + ("fichier importé" if fichier else "série simulée (21 jours) calée sur la capacité de la source") +
                   f" · type de source : {info['type']}")
        r = forecast.prevoir(serie, horizon, modele, info["capacite"] or None)
        histo = serie.tail(72)
        fig = go.Figure()
        fig.add_scatter(x=histo["horodatage"], y=histo["valeur"], name="Production mesurée", line=dict(color=VERT))
        p = r["prevision"]
        fig.add_scatter(x=p["horodatage"], y=p["haut"], line=dict(width=0), showlegend=False, hoverinfo="skip")
        fig.add_scatter(x=p["horodatage"], y=p["bas"], fill="tonexty", fillcolor="rgba(224,160,48,.25)", line=dict(width=0),
                        name="Marge d'incertitude")
        fig.add_scatter(x=p["horodatage"], y=p["prevision"], name="Prévision", line=dict(color=ORANGE, width=3, dash="dash"))
        fig.update_layout(yaxis_title="MW", legend=dict(orientation="h", y=-0.2), margin=dict(l=0, r=0, t=10, b=0), height=420)
        st.plotly_chart(fig, width="stretch")
        m1, m2 = st.columns(2)
        m1.metric("Énergie prévue", f"{r['energie_prevue']:.0f} MWh")
        m2.metric("Erreur moyenne du modèle (24 h testées)", f"{r['mae']:.2f} MW")
        with st.expander("Voir les valeurs prévues"):
            common.tableau(p)
    except SmartGridError as exc:
        common.erreur(exc)

# ------------------------------------------------------------------------------------ anomalies
with onglets[1]:
    common.phrase("Repérer les productions ou consommations anormales : sur une série de mesures, puis sur l'état actuel du réseau.")
    st.subheader("État actuel du réseau")
    alertes = anomalies.anomalies_reseau(store)
    if not alertes:
        st.success("Aucune alerte : le réseau fonctionne normalement.")
    icones = {"critique": ("🔴", st.error), "avertissement": ("🟠", st.warning), "information": ("🔵", st.info)}
    for a in alertes:
        icones[a["gravite"]][1](f"{icones[a['gravite']][0]} {a['message']}")

    st.subheader("Mesures dans le temps")
    c1, c2, c3 = st.columns(3)
    src = c1.selectbox("Source", list(noms_sources), format_func=lambda i: noms_sources[i], key="an_src")
    methode = c2.selectbox("Méthode", ["isolation", "zscore"], format_func={"isolation": "Forêt d'isolation (IsolationForest)", "zscore": "Écart au profil horaire (z-score)"}.get)
    inject = c3.checkbox("Ajouter des pannes artificielles pour la démonstration", value=True)
    serie = forecast.serie_simulee(src, anomalies=inject, store=store)
    res = anomalies.detecter_serie(serie, methode)
    fig = go.Figure()
    fig.add_scatter(x=res["horodatage"], y=res["valeur"], name="Production", line=dict(color=VERT))
    pts = res[res["anomalie"]]
    fig.add_scatter(x=pts["horodatage"], y=pts["valeur"], mode="markers", name="Anomalie", marker=dict(color=ROUGE, size=11, symbol="x"))
    fig.update_layout(yaxis_title="MW", legend=dict(orientation="h", y=-0.2), margin=dict(l=0, r=0, t=10, b=0), height=380)
    st.plotly_chart(fig, width="stretch")
    st.metric("Anomalies détectées", len(pts))
    if len(pts):
        common.tableau(pts[["horodatage", "valeur", "score"]].assign(valeur=pts["valeur"].round(3), score=pts["score"].round(3)))

# ------------------------------------------------------------------------------------ recommandations
with onglets[2]:
    common.phrase("Suggérer la meilleure source pour un bâtiment sans alimentation, et repérer les sources surchargées.")
    sans = recommend.batiments_sans_alimentation(store)
    st.subheader("Bâtiments sans alimentation")
    if sans.empty:
        st.success("Tous les bâtiments sont alimentés.")
    else:
        b = st.selectbox("Bâtiment", sans["batiment"].tolist(),
                         format_func=lambda i: f"{sans.set_index('batiment').loc[i, 'nom']} ({sans.set_index('batiment').loc[i, 'consommation']:g} MW)")
        reco = recommend.recommander(b, store)
        st.caption("Score sur 100 = capacité restante (40 %) + proximité du nœud (35 %) + énergie renouvelable (25 %).")
        common.tableau(reco.rename(columns={"nom": "Source", "score": "Score", "puissance_disponible": "Puissance disponible (MW)",
                                            "raison": "Pourquoi"})[["Source", "Score", "Puissance disponible (MW)", "Pourquoi"]])
        compat = reco[reco["compatible"]]
        if len(compat):
            meilleure = compat.iloc[0]
            st.success(f"Source recommandée : **{meilleure['nom']}** (score {meilleure['score']}).")
            if common.est_admin() and st.button(f"Alimenter ce bâtiment avec « {meilleure['nom']} »"):
                try:
                    op = complex_ops.reaffecter_batiment(b, meilleure["source"], store)
                    st.success(op.message)
                    common.voir_sparql(op.sparql)
                except SmartGridError as exc:
                    common.erreur(exc)
        else:
            st.warning("Aucune source n'a assez de puissance disponible pour ce bâtiment.")
    st.subheader("Sources surchargées")
    sur = recommend.sources_surchargees(store)
    if not sur.empty:
        aff = sur.copy()
        aff["charge"] = aff["charge"].map(lambda c: "∞" if c == float("inf") else f"{c:.0%}")
        aff = aff.rename(columns={"nom": "Source", "production": "Production (MW)", "consommation_servie": "Consommation servie (MW)",
                                  "charge": "Charge", "statut": "Statut"})
        common.tableau(aff[["Source", "Production (MW)", "Consommation servie (MW)", "Charge", "Statut"]])
        for _, r in sur[sur["statut"] == "Surchargée"].iterrows():
            st.error(f"🔴 « {r['nom']} » alimente plus de consommation ({r['consommation_servie']:.1f} MW) qu'elle ne produit ({r['production']:.1f} MW).")

# ------------------------------------------------------------------------------------ simulation
with onglets[3]:
    common.phrase("Tester un scénario sans toucher aux données réelles : ajouter un bâtiment ou simuler la panne d'une source.")
    type_ = st.radio("Scénario", ["Ajouter un bâtiment", "Panne d'une source"], horizontal=True)
    if type_ == "Ajouter un bâtiment":
        c1, c2, c3 = st.columns(3)
        conso = c1.number_input("Consommation (MW)", 0.1, 500.0, 5.0)
        src = c2.selectbox("Source qui l'alimente", [""] + list(noms_sources), format_func=lambda i: noms_sources.get(i, "(aucune : voir la recommandation)"))
        noeud = c3.selectbox("Nœud", [""] + [i["id"] for i in crud.lister_ids("GridNode", store)], format_func=lambda x: x or "(aucun)")
        scenario = {"type": "ajout_batiment", "consommation": conso, "source": src or None, "noeud": noeud or None}
    else:
        src = st.selectbox("Source en panne", list(noms_sources), format_func=lambda i: noms_sources[i], key="sim_src")
        reaff = st.checkbox("Basculer automatiquement les bâtiments touchés sur la meilleure autre source", value=True)
        scenario = {"type": "panne_source", "source": src, "reaffecter": reaff}
    if st.button("▶️ Lancer la simulation", type="primary"):
        try:
            st.session_state["simulation"] = simulation.simuler(scenario, store)
        except SmartGridError as exc:
            common.erreur(exc)
    s = st.session_state.get("simulation")
    if s:
        for n in s["notes"]:
            st.write("• " + n)
        a, b = s["avant"], s["apres"]
        fig = go.Figure()
        fig.add_bar(x=["Production", "Consommation", "Bilan"], y=[a["production"], a["consommation"], a["bilan"]], name="Avant", marker_color="#b9d6cd")
        fig.add_bar(x=["Production", "Consommation", "Bilan"], y=[b["production"], b["consommation"], b["bilan"]], name="Après", marker_color=ORANGE)
        fig.update_layout(barmode="group", yaxis_title="MW", margin=dict(l=0, r=0, t=10, b=0), height=340)
        st.plotly_chart(fig, width="stretch")
        c1, c2, c3 = st.columns(3)
        c1.metric("Bilan avant", f"{a['bilan']:.1f} MW")
        c2.metric("Bilan après", f"{b['bilan']:.1f} MW", delta=f"{s['ecart_bilan']:+.1f} MW")
        c3.metric("Sans alimentation après", len(b["batiments_sans_alimentation"]))
        if b["sources_surchargees"]:
            st.error("Sources surchargées après le scénario : " + ", ".join(b["sources_surchargees"]))
        if b["batiments_sans_alimentation"]:
            st.warning("Bâtiments sans alimentation : " + ", ".join(b["batiments_sans_alimentation"]))
