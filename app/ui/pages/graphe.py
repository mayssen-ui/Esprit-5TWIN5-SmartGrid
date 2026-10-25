"""Visualisation interactive du graphe de connaissances (pyvis) : couleurs par catégorie, filtres, clic sur un nœud."""
import html as html_lib

import streamlit as st
import streamlit.components.v1 as components
from pyvis.network import Network

from app.labels import libelle_prop, nom_classe
from app.sparql.schema import get_schema
from app.sparql.store import get_store
from app.ui import common

common.exiger_connexion()
store = get_store()
schema = get_schema()
st.title("🕸️ Graphe du réseau")
common.phrase("Visualiser les éléments du réseau (points) et leurs liens (flèches). Cliquez sur un point pour voir ses informations.")

COULEURS = {
    "EnergySource": "#e0a030", "Building": "#3b7dd8", "EnergyStorage": "#7a5cc2", "GridNode": "#1f6f5c",
    "Substation": "#c4553d", "Energy": "#4aa3a2", "User": "#8c8c8c",
}
RACINES = ["EnergySource", "Building", "EnergyStorage", "GridNode", "Substation", "Energy", "User"]


def racine_de(cls: str) -> str:
    for r in RACINES:
        if schema.est_sous_classe(cls, r):
            return r
    return "User"


requete_liens = """SELECT ?s ?p ?o WHERE {
  ?s ?p ?o . ?s a owl:NamedIndividual . ?o a owl:NamedIndividual .
  FILTER(?p != rdf:type)
}"""
requete_noeuds = """SELECT ?id ?nom ?t WHERE { ?id a owl:NamedIndividual ; a ?t . OPTIONAL { ?id sg:hasName ?nom }
  FILTER(?t != owl:NamedIndividual) }"""
requete_donnees = "SELECT ?id ?p ?v WHERE { ?id ?p ?v . FILTER(isLiteral(?v)) }"

c1, c2, c3 = st.columns([3, 2, 2])
choix = c1.multiselect("Catégories à afficher", RACINES, default=[r for r in RACINES if r != "Energy"],
                       format_func=lambda c: nom_classe(c, True).capitalize())
physique = c2.checkbox("Animation (physique)", value=True)
etiquettes = c3.checkbox("Afficher les noms", value=True)
liens_voulus = st.multiselect("Types de liens à afficher", sorted(p.nom for p in schema.props.values() if p.type == "object"),
                              default=sorted(p.nom for p in schema.props.values() if p.type == "object"),
                              format_func=libelle_prop)

types = {}
for r in store.query(requete_noeuds).rows:
    cls = r["t"]
    if cls in schema.classes and (r["id"] not in types or len(schema.ancetres(cls)) > len(schema.ancetres(types[r["id"]]["classe"]))):
        types[r["id"]] = {"classe": cls, "nom": r["nom"] or r["id"]}
donnees: dict[str, list[str]] = {}
for r in store.query(requete_donnees).rows:
    if r["p"] in schema.props:
        donnees.setdefault(r["id"], []).append(f"<b>{html_lib.escape(libelle_prop(r['p']))}</b> : {html_lib.escape(str(r['v']))}")

reseau = Network(height="640px", width="100%", directed=True, cdn_resources="remote", bgcolor="#ffffff")
visibles = {i for i, d in types.items() if racine_de(d["classe"]) in choix}
for i in visibles:
    d = types[i]
    racine = racine_de(d["classe"])
    detail = (f"<h3>{html_lib.escape(d['nom'])}</h3><i>{html_lib.escape(nom_classe(d['classe']))}</i> · <code>{i}</code><br><br>"
              + "<br>".join(donnees.get(i, ["(aucune caractéristique)"])))
    reseau.add_node(i, label=d["nom"] if etiquettes else " ", color=COULEURS[racine], details=detail, title=d["nom"],
                    shape="dot", size=22 if racine in ("GridNode", "Substation") else 16)
nb_liens = 0
for r in store.query(requete_liens).rows:
    if r["p"] in liens_voulus and r["s"] in visibles and r["o"] in visibles:
        reseau.add_edge(r["s"], r["o"], label=libelle_prop(r["p"]) if etiquettes else "", title=libelle_prop(r["p"]),
                        color="#9aa5a1", arrows="to")
        nb_liens += 1
reseau.toggle_physics(physique)
reseau.set_options('{"edges": {"font": {"size": 9, "align": "middle"}, "smooth": {"type": "dynamic"}}, '
                   '"interaction": {"hover": true, "navigationButtons": true}}')
page = reseau.generate_html()
panneau = """
<div id="infos" style="position:absolute;top:10px;right:10px;width:300px;max-height:600px;overflow:auto;background:#fffffff2;
  border:1px solid #cfd8d5;border-radius:8px;padding:10px;font-family:sans-serif;font-size:13px;color:#222;display:none"></div>
<script>
network.on("click", function (p) {
  var d = document.getElementById("infos");
  if (p.nodes.length) { var n = nodes.get(p.nodes[0]); d.innerHTML = n.details; d.style.display = "block"; }
  else { d.style.display = "none"; }
});
</script>
"""
page = page.replace("</body>", panneau + "</body>")
st.caption(f"{len(visibles)} élément(s) et {nb_liens} lien(s) affichés.")
components.html(page, height=670, scrolling=False)

cols = st.columns(len(choix) or 1)
for col, r in zip(cols, choix):
    col.markdown(f"<span style='color:{COULEURS[r]};font-size:20px'>●</span> {nom_classe(r, True).capitalize()}", unsafe_allow_html=True)
common.voir_sparql(requete_liens, "Voir la requête SPARQL (liens)")
common.voir_sparql(requete_noeuds, "Voir la requête SPARQL (éléments)")
