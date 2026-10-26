"""Poser une question en français : traduction automatique en SPARQL, résultats et correction manuelle."""
import streamlit as st

from app.ui import backend
from app.services import history
from app.sparql.store import get_store
from app.ui import common

user = common.exiger_connexion()
store = get_store()
st.title("💬 Poser une question")
common.phrase("Écrivez une phrase en français (ou en anglais) : elle est traduite en requête SPARQL, exécutée, puis expliquée.")

EXEMPLES = [
    "Citer les différents bâtiments",
    "Quels bâtiments sont alimentés par une ferme solaire ?",
    "Combien de sources éoliennes y a-t-il ?",
    "Quelle est la consommation totale des bâtiments industriels ?",
    "Citer les bâtiments alimentés par une source d'énergie renouvelable",
    "Quels utilisateurs possèdent des bâtiments industriels ?",
    "Top 3 des plus gros consommateurs",
    "Ajouter une batterie nommée Batterie Sousse de capacité 12",
]

st.caption("Exemples (cliquez pour les essayer) :")
cols = st.columns(4)
for i, ex in enumerate(EXEMPLES):
    if cols[i % 4].button(ex, key=f"ex{i}", width="stretch"):
        st.session_state["question"] = ex
        st.session_state.pop("sortie", None)

question = st.text_input("Votre question", key="question", placeholder="Ex. : Quelles sont les sources éoliennes ?")
col_a, col_b = st.columns([1, 5])
if col_a.button("Poser la question", type="primary") and question:
    st.session_state["sortie"] = backend.repondre(question, store=store, peut_ecrire=common.est_admin(),
                                                    utilisateur=user["email"])
    s = st.session_state["sortie"]
    history.ajouter_historique(s["sparql"], question, len(s["resultat"]["rows"]) if s["resultat"] else None, s["erreur"])
col_b.caption("Analyse du français avec spaCy (lemmes, syntaxe, entités) puis rapprochement TF-IDF avec des requêtes modèles.")

sortie = st.session_state.get("sortie")
if sortie and sortie["question"] == question:
    niveaux = {"regles": "règles intégrées", "similarite": "similarité TF-IDF avec une requête modèle", "edite": "requête corrigée à la main"}
    if sortie["erreur"] and not sortie["sparql"]:
        st.error(sortie["erreur"])
    else:
        if sortie["explication"]:
            common.phrase(sortie["explication"] + f"  _(traduit par : {niveaux.get(sortie['niveau'], sortie['niveau'])})_")
        if sortie["erreur"]:
            st.error(sortie["erreur"])
        if sortie["confirmation_requise"] and not sortie["execute"]:
            st.warning("⚠️ " + (sortie["message"] or "Cette demande modifie les données."))
            st.code(sortie["sparql"], language="sparql")
            if common.est_admin():
                if st.button("✅ Confirmer et exécuter la modification", type="primary"):
                    st.session_state["sortie"] = backend.repondre(question, confirmer=True, sparql=sortie["sparql"],
                                                                    store=store, peut_ecrire=True, utilisateur=user["email"])
                    st.rerun()
            else:
                st.info("🔒 Votre rôle (lecteur) ne permet pas de modifier les données.")
        elif sortie["execute"] and sortie["niveau"] != "edite" and sortie["resultat"] is None:
            st.success(sortie["message"])
        if sortie["resultat"]:
            res = sortie["resultat"]
            if res["kind"] == "ask":
                st.subheader("Oui" if res["boolean"] else "Non")
            else:
                st.success(sortie["message"])
                common.tableau(res["rows"])
                if sortie["tronque"]:
                    st.caption("Le nombre de résultats a été limité.")
        common.voir_sparql(sortie["sparql"])

        with st.expander("✏️ Corriger la requête"):
            st.caption("Modifiez la requête SPARQL si la traduction n'est pas exactement celle que vous souhaitiez.")
            corrigee = st.text_area("Requête SPARQL", sortie["sparql"], height=220, key="requete_corrigee")
            if st.button("Exécuter la requête corrigée"):
                st.session_state["sortie"] = {**backend.repondre(question, sparql=corrigee, store=store,
                                                                  peut_ecrire=common.est_admin(), utilisateur=user["email"])}
                st.rerun()
elif sortie:
    st.session_state.pop("sortie", None)

with st.expander("📜 Historique des traductions (journal)"):
    from app.ai.guardrails import lire_journal
    common.tableau([{"Date": e["date"], "Question": e.get("question"), "Niveau": e.get("niveau"),
                     "Exécutée": e.get("execute"), "Erreur": e.get("erreur")} for e in lire_journal(20)])
