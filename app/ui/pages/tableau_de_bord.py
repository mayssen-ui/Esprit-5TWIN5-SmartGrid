"""Tableau de bord : indicateurs clés et graphiques, tous calculés par des requêtes SPARQL agrégées."""
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from app.labels import nom_classe
from app.services import stats
from app.sparql.store import get_store
from app.ui import common

common.exiger_connexion()
store = get_store()
st.title("📊 Tableau de bord")

PALETTE = ["#1f6f5c", "#e0a030", "#3b7dd8", "#c4553d", "#7a5cc2", "#4aa3a2"]
VERT, ORANGE, BLEU, ROUGE = PALETTE[:4]

if st.button("🔄 Actualiser les chiffres"):
    st.rerun()

kpi = stats.indicateurs(store)
t = stats.tout_calculer(store)

st.subheader("Indicateurs clés")
common.phrase("Chiffres essentiels du réseau, calculés en direct.")
noms = list(kpi)
for ligne in (noms[:4], noms[4:8], noms[8:]):
    cols = st.columns(len(ligne))
    for c, n in zip(cols, ligne):
        c.metric(n, kpi[n])
common.voir_sparql(stats.STATS["kpi"].sparql)


def graphique(stat_id: str, fig, phrase_txt: str, df=None):
    common.phrase(phrase_txt)
    st.plotly_chart(fig, width="stretch")
    with st.expander("Voir les chiffres"):
        common.tableau(t[stat_id] if df is None else df)
    common.voir_sparql(stats.STATS[stat_id].sparql)


def libelle_classe(c):
    return nom_classe(c, True).capitalize()


c1, c2 = st.columns(2)
with c1:
    st.subheader("Éléments par catégorie")
    d = t["individus_par_classe"].copy()
    d["Catégorie"] = d["classe"].map(libelle_classe)
    fig = px.bar(d, x="nombre", y="Catégorie", orientation="h", text="nombre", color_discrete_sequence=[VERT])
    fig.update_layout(yaxis={"categoryorder": "total ascending"}, margin=dict(l=0, r=0, t=10, b=0), height=420, xaxis_title="Nombre d'éléments")
    graphique("individus_par_classe", fig, "Compter les éléments de chaque catégorie.", d[["Catégorie", "nombre"]])
with c2:
    st.subheader("Types de bâtiments")
    d = t["types_batiments"].copy()
    d["Type"] = d["type"].map(libelle_classe)
    fig = px.pie(d, names="Type", values="nombre", hole=0.45, color_discrete_sequence=PALETTE)
    fig.update_layout(margin=dict(l=0, r=0, t=10, b=0), height=420)
    graphique("types_batiments", fig, "Répartir les bâtiments selon leur usage.", d[["Type", "nombre"]])

st.subheader("Sources d'énergie : capacité, production et utilisation")
d = t["sources_capacite_production"].copy()
fig = go.Figure()
fig.add_bar(x=d["nom"], y=d["capacite"], name="Capacité installée (MW)", marker_color="#b9d6cd")
fig.add_bar(x=d["nom"], y=d["production"], name="Production réelle (MW)", marker_color=VERT)
fig.add_scatter(x=d["nom"], y=d["taux_utilisation"] * 100, name="Taux d'utilisation (%)", yaxis="y2", mode="lines+markers",
                line=dict(color=ORANGE, width=3))
fig.update_layout(barmode="group", yaxis=dict(title="MW"), yaxis2=dict(title="%", overlaying="y", side="right", range=[0, 110]),
                  legend=dict(orientation="h", y=-0.25), margin=dict(l=0, r=0, t=10, b=0), height=420)
graphique("sources_capacite_production", fig, "Comparer ce que chaque source peut produire et ce qu'elle produit réellement.")

c1, c2 = st.columns(2)
with c1:
    st.subheader("Énergie renouvelable ou non")
    d = t["renouvelable_vs_non"]
    fig = px.pie(d, names="categorie", values="production", hole=0.45, color="categorie",
                 color_discrete_map={"Renouvelable": VERT, "Non renouvelable": ROUGE})
    fig.update_layout(margin=dict(l=0, r=0, t=10, b=0), height=360)
    graphique("renouvelable_vs_non", fig, f"Part de la production d'origine renouvelable : {kpi['Part renouvelable (%)']} %.")
with c2:
    st.subheader("Consommation par type de bâtiment")
    d = t["consommation_par_type"].copy()
    d["Type"] = d["type"].map(libelle_classe)
    fig = px.bar(d, x="Type", y="consommation", text_auto=".2f", color_discrete_sequence=[BLEU])
    fig.update_layout(margin=dict(l=0, r=0, t=10, b=0), height=360, yaxis_title="MW")
    graphique("consommation_par_type", fig, "Additionner la consommation de chaque type de bâtiment.", d[["Type", "consommation", "nombre"]])

st.subheader("Les 5 plus gros consommateurs")
d = t["top_consommateurs"].copy()
d["Type"] = d["type"].map(lambda c: nom_classe(c).capitalize())
fig = px.bar(d, x="consommation", y="nom", orientation="h", color="Type", color_discrete_sequence=PALETTE, text_auto=".2f")
fig.update_layout(yaxis={"categoryorder": "total ascending"}, margin=dict(l=0, r=0, t=10, b=0), height=340, xaxis_title="MW", yaxis_title="")
graphique("top_consommateurs", fig, "Citer les 5 bâtiments qui consomment le plus.", d[["nom", "Type", "consommation"]])

st.subheader("Bilan production / consommation")
c1, c2 = st.columns([1, 2])
with c1:
    b = t["bilan_global"].iloc[0]
    st.metric("Production totale", f"{b['production']:.1f} MW")
    st.metric("Consommation totale", f"{b['consommation']:.1f} MW")
    st.metric("Bilan", f"{b['bilan']:.1f} MW", delta="excédent" if b["bilan"] >= 0 else "déficit")
    common.voir_sparql(stats.STATS["bilan_global"].sparql)
with c2:
    d = t["bilan_par_noeud"]
    fig = go.Figure()
    fig.add_bar(x=d["nom"], y=d["production"], name="Production", marker_color=VERT)
    fig.add_bar(x=d["nom"], y=d["consommation"], name="Consommation", marker_color=ORANGE)
    fig.add_scatter(x=d["nom"], y=d["bilan"], name="Bilan", mode="lines+markers", line=dict(color=BLEU, width=3))
    fig.update_layout(barmode="group", legend=dict(orientation="h", y=-0.25), margin=dict(l=0, r=0, t=10, b=0), height=340, yaxis_title="MW")
    graphique("bilan_par_noeud", fig, "Comparer, nœud par nœud, ce qui est produit et ce qui est consommé.")

st.subheader("Stockage")
s = t["stockage"].iloc[0]
c1, c2, c3 = st.columns(3)
c1.metric("Nombre de stockages", int(s["nombre"] or 0))
c2.metric("Capacité totale stockée", f"{(s['capacite_totale'] or 0):.1f} MWh")
c3.metric("Efficacité moyenne", f"{(s['efficacite_moyenne'] or 0):.0%}")
common.phrase("Calculer la capacité totale et l'efficacité moyenne de toutes les batteries.")
common.voir_sparql(stats.STATS["stockage"].sparql)

c1, c2 = st.columns(2)
with c1:
    st.subheader("Nœuds par localisation")
    d = t["noeuds_par_localisation"]
    fig = px.bar(d, x="localisation", y="nombre", text="nombre", color_discrete_sequence=[VERT])
    fig.update_layout(margin=dict(l=0, r=0, t=10, b=0), height=300, xaxis_title="", yaxis_title="Nœuds")
    graphique("noeuds_par_localisation", fig, "Compter les nœuds du réseau dans chaque ville.")
with c2:
    st.subheader("Nœuds par niveau de tension")
    d = t["noeuds_par_tension"].copy()
    d["Tension"] = d["tension"].map(lambda v: f"{v:g} kV")
    fig = px.pie(d, names="Tension", values="nombre", hole=0.45, color_discrete_sequence=PALETTE)
    fig.update_layout(margin=dict(l=0, r=0, t=10, b=0), height=300)
    graphique("noeuds_par_tension", fig, "Répartir les nœuds selon leur tension.", d[["Tension", "nombre"]])

st.subheader("Exporter les statistiques")
e1, e2 = st.columns(2)
e1.download_button("⬇️ Télécharger en CSV", stats.export_csv(kpi, t), "statistiques_smartgrid.csv", "text/csv")
e2.download_button("⬇️ Télécharger le rapport PDF", stats.export_pdf(kpi, t), "rapport_smartgrid.pdf", "application/pdf")
