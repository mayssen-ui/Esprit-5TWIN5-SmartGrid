"""Raisonnement OWL (HermiT) : classes inférées et cohérence de l'ontologie."""
import streamlit as st

from app.services import reasoning
from app.sparql.store import get_store
from app.ui import common

common.exiger_connexion()
store = get_store()
st.title("🧠 Raisonnement")
common.phrase("Le raisonneur HermiT déduit de nouvelles informations à partir des règles de l'ontologie "
              "(par exemple : un bâtiment alimenté par une source renouvelable est un « bâtiment renouvelable »).")
st.caption("Le raisonnement travaille sur une copie : vos données ne sont pas modifiées.")

c1, c2 = st.columns([1, 3])
lancer = c1.button("🧠 Lancer le raisonnement", type="primary")
repli = c2.checkbox("Utiliser le calcul SPARQL simplifié (sans Java)")
if lancer:
    with st.spinner("Le raisonneur travaille…"):
        st.session_state["raisonnement"] = reasoning.verifier_coherence(store) if not repli else reasoning.lancer_raisonnement(store, True)

r = st.session_state.get("raisonnement")
if r:
    st.caption(f"Moteur : {r['moteur']} · durée : {r['duree_s']} s")
    if r["coherent"] is True:
        st.success("✅ L'ontologie est cohérente : aucune contradiction détectée.")
    elif r["coherent"] is False:
        st.error("❌ L'ontologie est incohérente : " + (", ".join(r["classes_incoherentes"]) or "contradiction détectée."))
    else:
        st.warning("Cohérence non vérifiée (raisonneur HermiT indisponible : installez Java 11 ou plus).")

    st.subheader("Éléments classés automatiquement")
    renouv = [t for t in r["types_inferes"] if "RenewableBuilding" in t["types_ajoutes"]]
    common.phrase(f"{len(renouv)} bâtiment(s) sont déduits « alimentés par une source d'énergie renouvelable » (classe RenewableBuilding).")
    common.tableau([{"Élément": t["individu"], "Catégories déduites": ", ".join(t["types_ajoutes"])} for t in r["types_inferes"]])
    if r["sous_classes_inferees"]:
        st.subheader("Nouvelles relations entre catégories")
        common.tableau([{"Catégorie": s["classe"], "Devient aussi une sorte de": ", ".join(s["nouvelles_super_classes"])}
                        for s in r["sous_classes_inferees"]])
    if r["liens_inferes"]:
        st.subheader("Nouveaux liens déduits")
        common.tableau([{"Élément": l["sujet"], "Lien": l["propriete"], "Vers": l["objet"]} for l in r["liens_inferes"]])
    if r.get("journal"):
        with st.expander("Journal technique du raisonneur"):
            st.code(r["journal"])

st.subheader("Contrôle avec SPARQL")
common.phrase("Citer les bâtiments alimentés par une source d'énergie renouvelable (calcul direct, sans raisonneur).")
q = """SELECT DISTINCT ?nom WHERE {
  ?b a/rdfs:subClassOf* sg:Building ; sg:hasName ?nom ; sg:suppliedBy ?s .
  ?s sg:produces ?e . ?e a/rdfs:subClassOf* sg:RenewableEnergy .
} ORDER BY ?nom"""
common.tableau(store.query(q).rows)
common.voir_sparql(q)
