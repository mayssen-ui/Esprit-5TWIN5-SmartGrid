"""Requêtes croisées entre plusieurs classes, et opérations combinées (CRUD complexe)."""
import streamlit as st

from app.errors import SmartGridError
from app.labels import nom_classe
from app.services import complex_ops, crud, history
from app.sparql.queries import CATALOGUE
from app.sparql.store import get_store
from app.ui import common

common.exiger_connexion()
store = get_store()
st.title("🔗 Requêtes croisées")

onglets = st.tabs(["🔎 Interroger plusieurs éléments à la fois", "🛠️ Opérations combinées"])

# ---------------------------------------------------------------------------- requêtes
with onglets[0]:
    q = st.selectbox("Que voulez-vous savoir ?", CATALOGUE, format_func=lambda x: x.libelle)
    common.phrase(q.libelle + ".")
    st.caption(q.explication + ("  ·  Techniques SPARQL : " + ", ".join(q.techniques) if q.techniques else ""))
    try:
        res = store.query(q.sparql)
        history.ajouter_historique(q.sparql, q.libelle, len(res.rows))
        st.metric("Résultats", len(res.rows))
        common.tableau(res.rows)
    except Exception as exc:  # noqa: BLE001
        common.erreur(exc)
    common.voir_sparql(q.sparql)

    with st.expander("Toutes les requêtes en un coup d'œil"):
        for item in CATALOGUE:
            n = len(store.query(item.sparql).rows)
            st.write(f"**{item.libelle}** — {n} résultat(s)")

# ---------------------------------------------------------------------------- opérations
with onglets[1]:
    if not common.reserve_admin():
        st.stop()
    ids = lambda cls: [i["id"] for i in crud.lister_ids(cls, store)]  # noqa: E731

    st.subheader("1. Ajouter un bâtiment et le relier au réseau en une seule fois")
    common.phrase("Créer un bâtiment, l'alimenter par une source et le placer sur un nœud. Si une étape échoue, rien n'est enregistré.")
    with st.form("batiment_complet"):
        c1, c2 = st.columns(2)
        classe = c1.selectbox("Type de bâtiment", ["ResidentialBuilding", "CommercialBuilding", "IndustrialBuilding"],
                              format_func=lambda c: nom_classe(c), index=1)
        nom = c2.text_input("Nom *")
        conso = c1.text_input("Consommation (MW)")
        source = c2.selectbox("Source qui l'alimente", [""] + ids("EnergySource"), format_func=lambda x: x or "(aucune)")
        noeud = c1.selectbox("Nœud du réseau", [""] + ids("GridNode"), format_func=lambda x: x or "(aucun)")
        batterie = c2.selectbox("Batterie", [""] + ids("EnergyStorage"), format_func=lambda x: x or "(aucune)")
        ok = st.form_submit_button("Créer et relier", type="primary")
    if ok:
        try:
            op = complex_ops.creer_batiment_lie(classe, {"hasName": nom, "hasConsumption": conso}, source or None,
                                                noeud or None, batterie or None, store)
            st.success(op.message)
            common.voir_sparql(op.sparql)
        except SmartGridError as exc:
            common.erreur(exc)
            st.caption("Aucune modification n'a été enregistrée (retour en arrière automatique).")

    st.subheader("2. Changer la source d'un bâtiment")
    common.phrase("Réaffecter un bâtiment à une autre source d'énergie.")
    with st.form("reaffecter"):
        c1, c2 = st.columns(2)
        b = c1.selectbox("Bâtiment", ids("Building"))
        s = c2.selectbox("Nouvelle source", ids("EnergySource"))
        ok = st.form_submit_button("Réaffecter", type="primary")
    if ok:
        try:
            op = complex_ops.reaffecter_batiment(b, s, store)
            st.success(op.message)
            common.voir_sparql(op.sparql)
        except SmartGridError as exc:
            common.erreur(exc)

    st.subheader("3. Supprimer une source en détachant ses bâtiments")
    common.phrase("Supprimer une source d'énergie : les bâtiments et nœuds qui y étaient liés sont détachés.")
    s = st.selectbox("Source à supprimer", ids("EnergySource"), key="src_sup")
    liés = store.query(f"SELECT ?nom WHERE {{ ?b sg:suppliedBy sg:{s} ; sg:hasName ?nom }}").rows
    if liés:
        st.warning("Bâtiments qui seront sans alimentation : " + ", ".join(r["nom"] for r in liés))
    conf = st.checkbox("Je confirme la suppression de cette source", key="conf_src")
    if st.button("Supprimer la source", disabled=not conf):
        try:
            op = complex_ops.supprimer_source_detachee(s, store)
            st.success(op.message)
            common.voir_sparql(op.sparql)
        except SmartGridError as exc:
            common.erreur(exc)

    st.subheader("4. Affecter un utilisateur à plusieurs bâtiments")
    common.phrase("Donner à un utilisateur la propriété de plusieurs bâtiments.")
    with st.form("affecter"):
        u = st.selectbox("Utilisateur", ids("User"))
        bs = st.multiselect("Bâtiments", ids("Building"))
        remplacer = st.checkbox("Remplacer ses affectations actuelles (sinon, ajouter)")
        ok = st.form_submit_button("Affecter", type="primary")
    if ok:
        try:
            op = complex_ops.affecter_utilisateur(u, bs, remplacer, store)
            st.success(op.message)
            common.voir_sparql(op.sparql)
        except SmartGridError as exc:
            common.erreur(exc)
