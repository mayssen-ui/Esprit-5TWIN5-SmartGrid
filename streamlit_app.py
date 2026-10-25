"""Point d'entrée Streamlit : menu latéral multi-pages.

Lancement :  streamlit run streamlit_app.py
"""
import streamlit as st

st.set_page_config(page_title="SmartGrid Sémantique", page_icon="⚡", layout="wide")

PAGES = {
    "Accueil": [st.Page("app/ui/pages/accueil.py", title="Accueil", icon=":material/home:", default=True)],
    "Gérer le réseau": [
        st.Page("app/ui/pages/gestion.py", title="Gérer les éléments", icon=":material/edit_note:"),
        st.Page("app/ui/pages/requetes_croisees.py", title="Requêtes croisées", icon=":material/hub:"),
        st.Page("app/ui/pages/question.py", title="Poser une question", icon=":material/chat:"),
        st.Page("app/ui/pages/editeur_sparql.py", title="Éditeur SPARQL", icon=":material/code:"),
    ],
    "Analyser": [
        st.Page("app/ui/pages/tableau_de_bord.py", title="Tableau de bord", icon=":material/bar_chart:"),
        st.Page("app/ui/pages/graphe.py", title="Graphe du réseau", icon=":material/account_tree:"),
        st.Page("app/ui/pages/raisonnement.py", title="Raisonnement", icon=":material/psychology:"),
    ],
    "Intelligence artificielle": [
        st.Page("app/ui/pages/assistant.py", title="Assistant SmartGrid", icon=":material/smart_toy:"),
        st.Page("app/ui/pages/ia.py", title="Prévisions, alertes, simulation", icon=":material/insights:"),
    ],
    "Données": [st.Page("app/ui/pages/import_export.py", title="Import / export", icon=":material/import_export:")],
}

st.navigation(PAGES).run()
