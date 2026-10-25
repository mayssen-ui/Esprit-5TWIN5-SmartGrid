"""Import / export : RDF/XML, Turtle, JSON-LD, N-Triples, CSV et import en masse d'individus."""
import streamlit as st

from app.errors import SmartGridError
from app.labels import nom_classe
from app.services import io_service
from app.sparql.schema import get_schema
from app.sparql.store import get_store
from app.ui import common

common.exiger_connexion()
store = get_store()
schema = get_schema()
st.title("📦 Import / export")

st.subheader("Exporter")
common.phrase("Télécharger tout le réseau dans le format de votre choix.")
cols = st.columns(len(io_service.FORMATS))
for col, (cle, (_, mime, ext, nom)) in zip(cols, io_service.FORMATS.items()):
    contenu, _, _ = io_service.exporter_graphe(cle, store)
    col.download_button(f"⬇️ {nom}", contenu, f"smartgrid{ext}", mime, width="stretch")

common.phrase("Télécharger la liste d'une catégorie au format CSV (ouvrable dans Excel).")
c1, c2 = st.columns([2, 1])
cat = c1.selectbox("Catégorie", [c for c in schema.classes if not schema.classes[c]["definie"]],
                   format_func=lambda c: nom_classe(c, True).capitalize())
c2.download_button("⬇️ Exporter en CSV", io_service.exporter_csv(cat, store), f"{cat}.csv", "text/csv", width="stretch")

st.divider()
st.subheader("Importer")
if common.reserve_admin():
    onglets = st.tabs(["Fichier RDF", "CSV (import en masse)"])
    with onglets[0]:
        common.phrase("Ajouter au réseau les informations d'un fichier RDF (elles sont fusionnées avec l'existant).")
        fmt = st.selectbox("Format du fichier", list(io_service.FORMATS), format_func=lambda k: io_service.FORMATS[k][3])
        fichier = st.file_uploader("Fichier RDF", type=["owl", "rdf", "xml", "ttl", "jsonld", "json", "nt"], key="rdf")
        if fichier and st.button("Importer le fichier RDF", type="primary"):
            try:
                st.success(io_service.importer_rdf(fichier.getvalue(), fmt, store)["message"])
            except SmartGridError as exc:
                common.erreur(exc)
    with onglets[1]:
        common.phrase("Créer plusieurs éléments d'un coup à partir d'un tableau CSV.")
        concretes = [c for c in schema.classes if not schema.classes[c]["definie"]]
        cible = st.selectbox("Catégorie des éléments", concretes, index=concretes.index("BatteryStorage"),
                             format_func=lambda c: nom_classe(c, True).capitalize(), key="csv_cat")
        champs = [c["nom"] for c in __import__("app.services.crud", fromlist=["x"]).champs_formulaire(cible, store)]
        modele = ";".join(["id"] + champs) + "\n"
        st.download_button("⬇️ Télécharger un modèle de fichier", ("﻿" + modele).encode("utf-8"), f"modele_{cible}.csv", "text/csv")
        st.caption("Colonnes : `id` (facultatif) puis une colonne par caractéristique. Plusieurs liens dans une même case : séparés par `|`.")
        tout = st.checkbox("Tout ou rien : n'importer que si toutes les lignes sont valides", value=True)
        fichier = st.file_uploader("Fichier CSV", type=["csv"], key="csv")
        if fichier and st.button("Importer le CSV", type="primary"):
            try:
                res = io_service.importer_csv(fichier.getvalue(), cible, store, tout)
                (st.success if res["crees"] else st.warning)(res["message"])
                if res["erreurs"]:
                    common.tableau([{"Ligne": e["ligne"], "Problème": e["message"]} for e in res["erreurs"]])
            except SmartGridError as exc:
                common.erreur(exc)
