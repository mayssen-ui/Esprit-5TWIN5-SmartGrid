"""Éditeur SPARQL libre : coloration syntaxique, résultats exportables, historique et favoris."""
import json

import pandas as pd
import streamlit as st

from app.ai import guardrails
from app.errors import QueryRejected, SmartGridError
from app.services import history
from app.sparql.prefixes import PREFIXES
from app.sparql.store import get_store
from app.ui import common

user = common.exiger_connexion()
store = get_store()
st.title("🧪 Éditeur SPARQL")
common.phrase("Écrire vos propres requêtes SPARQL (lecture pour tous, modification réservée aux administrateurs).")

EXEMPLE = """SELECT ?batiment ?nom ?consommation
WHERE {
  ?batiment a/rdfs:subClassOf* sg:Building ;
            sg:hasName ?nom ;
            sg:hasConsumption ?consommation .
}
ORDER BY DESC(?consommation)"""

if "editeur" not in st.session_state:
    st.session_state["editeur"] = EXEMPLE

colg, cold = st.columns([3, 2])
with cold:
    st.subheader("⭐ Favoris")
    for f in history.favoris():
        c1, c2 = st.columns([4, 1])
        if c1.button(f["nom"], key=f"fav_{f['nom']}", width="stretch"):
            st.session_state["editeur"] = f["requete"]
            st.session_state["editeur_v"] = st.session_state.get("editeur_v", 0) + 1
            st.rerun()
        if c2.button("🗑️", key=f"delfav_{f['nom']}"):
            history.supprimer_favori(f["nom"])
            st.rerun()
    st.subheader("🕘 Historique")
    for i, h in enumerate(history.historique(8)):
        if st.button(f"{h['date'][5:16]} · {(h['libelle'] or h['requete'])[:40]}", key=f"h{i}", width="stretch"):
            st.session_state["editeur"] = h["requete"]
            st.session_state["editeur_v"] = st.session_state.get("editeur_v", 0) + 1
            st.rerun()

with colg:
    st.caption("Préfixes disponibles sans les déclarer : `sg:`, `rdf:`, `rdfs:`, `owl:`, `xsd:`")
    cle = f"ace_{st.session_state.get('editeur_v', 0)}"
    try:
        from streamlit_ace import st_ace
        requete = st_ace(value=st.session_state["editeur"], language="sql", theme="chrome", height=280,
                         auto_update=True, key=cle, show_gutter=True, wrap=True)
    except Exception:  # composant indisponible : zone de texte simple
        requete = st.text_area("Requête SPARQL", st.session_state["editeur"], height=280, key=cle)
    st.session_state["editeur"] = requete or ""
    c1, c2, c3 = st.columns(3)
    lancer = c1.button("▶️ Exécuter", type="primary")
    nom_fav = c2.text_input("Nom du favori", label_visibility="collapsed", placeholder="Nom du favori")
    if c3.button("⭐ Ajouter aux favoris") and nom_fav and requete:
        history.ajouter_favori(nom_fav, requete)
        st.rerun()

    if lancer and requete:
        try:
            analyse = guardrails.analyser(requete)
            if analyse.type == "update":
                if not common.est_admin():
                    st.error("Votre rôle (lecteur) ne permet pas de modifier les données.")
                else:
                    st.session_state["maj_en_attente"] = requete
            else:
                res = store.query(analyse.requete)
                history.ajouter_historique(analyse.requete, "Éditeur SPARQL", len(res.rows))
                st.session_state["resultat_editeur"] = res.to_dict()
                st.session_state.pop("maj_en_attente", None)
        except (QueryRejected, SmartGridError) as exc:
            common.erreur(exc)
        except Exception as exc:  # noqa: BLE001
            st.error(f"La requête n'a pas pu être exécutée : {str(exc)[:200]}")

    if st.session_state.get("maj_en_attente") == requete:
        st.warning("Cette requête modifie les données.")
        if st.button("✅ Confirmer la modification", type="primary"):
            store.update(requete)
            history.ajouter_historique(requete, "Modification (éditeur)")
            st.success("La modification a été enregistrée.")
            st.session_state.pop("maj_en_attente")

    res = st.session_state.get("resultat_editeur")
    if res:
        if res["kind"] == "ask":
            st.subheader("Oui" if res["boolean"] else "Non")
        else:
            df = pd.DataFrame(res["rows"], columns=res["vars"])
            st.success(f"{len(df)} résultat(s).")
            common.tableau(df)
            e1, e2 = st.columns(2)
            e1.download_button("⬇️ Exporter en CSV", ("﻿" + df.to_csv(index=False, sep=";")).encode("utf-8"),
                               "resultat_sparql.csv", "text/csv")
            e2.download_button("⬇️ Exporter en JSON", json.dumps(res["rows"], ensure_ascii=False, indent=1).encode("utf-8"),
                               "resultat_sparql.json", "application/json")
    with st.expander("Voir les préfixes ajoutés automatiquement"):
        st.code(PREFIXES, language="sparql")
