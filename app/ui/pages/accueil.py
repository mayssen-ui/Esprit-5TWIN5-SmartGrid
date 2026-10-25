"""Page d'accueil : connexion, résumé du réseau, guide des pages."""
import streamlit as st

from app.config import settings
from app.services import stats
from app.sparql.store import get_store
from app.ui import common

common.initialiser()
st.title("⚡ SmartGrid Sémantique")
st.write("Gérez, interrogez et analysez votre réseau électrique intelligent à partir de son ontologie, "
         "en français et sans connaître le langage SPARQL.")

u = common.utilisateur()
if not u:
    st.subheader("Connexion")
    common.phrase("Choisissez votre compte (les comptes sont les utilisateurs de l'ontologie) puis saisissez le mot de passe de votre rôle.")
    common.formulaire_connexion()
    st.caption("Mots de passe par défaut : voir le fichier `.env` (administrateur : `admin123`, lecteur : `lecteur123`).")
    st.stop()

st.success(f"Bonjour {u['nom']} ! Rôle : **{u['role']}**" + (" — vous pouvez tout modifier." if u["role"] == "admin" else " — lecture seule."))
common.phrase("Voici l'état actuel du réseau.")
k = stats.indicateurs(get_store())
cols = st.columns(4)
for col, nom in zip(cols, ["Éléments dans le réseau", "Bâtiments", "Sources d'énergie", "Nœuds du réseau"]):
    col.metric(nom, k[nom])
cols = st.columns(4)
for col, nom in zip(cols, ["Production (MW)", "Consommation (MW)", "Bilan (MW)", "Part renouvelable (%)"]):
    col.metric(nom, k[nom])
common.voir_sparql(stats.STATS["kpi"].sparql)

st.subheader("Que voulez-vous faire ?")
st.markdown("""
| Page | À quoi elle sert |
|---|---|
| **Gérer les éléments** | Consulter, ajouter, modifier ou supprimer des bâtiments, sources, batteries, nœuds, utilisateurs… |
| **Requêtes croisées** | Relier plusieurs types d'éléments (bâtiments ↔ sources ↔ nœuds…) et réaliser des opérations combinées. |
| **Poser une question** | Écrire une phrase en français ; l'application la traduit en requête et répond. |
| **Éditeur SPARQL** | Pour les spécialistes : écrire ses propres requêtes, garder un historique et des favoris. |
| **Tableau de bord** | Statistiques et graphiques, export CSV / PDF. |
| **Graphe du réseau** | Visualiser les liens entre les éléments. |
| **Raisonnement** | Vérifier la cohérence de l'ontologie et voir ce que le raisonneur déduit. |
| **Assistant SmartGrid** | Discuter avec un assistant qui s'appuie sur le graphe. |
| **Prévisions, alertes, simulation** | Prévoir la production, détecter les anomalies, recommander des sources, tester des scénarios. |
| **Import / export** | Échanger des données (RDF/XML, Turtle, JSON-LD, CSV). |
""")
st.caption(f"Moteur de stockage : **{settings.backend}** · Assistant IA : "
           f"{'activé' if settings.anthropic_key else 'non configuré (les règles intégrées restent disponibles)'}")
