"""Éléments d'interface partagés par toutes les pages Streamlit."""
from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from app.errors import IntegrityError, SmartGridError, ValidationError
from app.services import auth
from app.sparql.store import get_store

COULEUR = "#1f6f5c"

CSS = """
<style>
.phrase {border-left: 4px solid #1f6f5c; padding: .4rem .9rem; margin: .2rem 0 .8rem 0;
         background: rgba(31,111,92,.08); border-radius: 0 6px 6px 0; font-size: 1.02rem;}
div[data-testid="stMetric"] {background: rgba(31,111,92,.07); padding: .6rem .9rem; border-radius: 8px;}
</style>
"""


def initialiser() -> None:
    """Appelé en tête de chaque page : style commun et barre latérale de connexion."""
    st.markdown(CSS, unsafe_allow_html=True)
    barre_laterale_session()


def phrase(texte: str) -> None:
    """Affiche la phrase en langage naturel qui décrit l'action réalisée par le bloc."""
    st.markdown(f'<div class="phrase">💬 {texte}</div>', unsafe_allow_html=True)


def voir_sparql(requete: str, titre: str = "Voir la requête SPARQL") -> None:
    """Expander « Voir la requête SPARQL »."""
    if requete:
        with st.expander(titre):
            st.code(requete, language="sparql")


def tableau(donnees: Any, **kw) -> None:
    """Tableau pleine largeur ; accepte une liste de dictionnaires ou un DataFrame."""
    df = donnees if isinstance(donnees, pd.DataFrame) else pd.DataFrame(donnees)
    if df.empty:
        st.info("Aucun résultat à afficher.")
        return
    st.dataframe(df, hide_index=True, width="stretch", **kw)


def erreur(exc: Exception) -> None:
    """Affiche une erreur métier en langage clair (jamais de trace technique)."""
    if isinstance(exc, ValidationError) and len(exc.erreurs) > 1:
        st.error("Certaines valeurs sont à corriger :\n\n" + "\n".join(f"- {e}" for e in exc.erreurs))
    elif isinstance(exc, SmartGridError):
        st.error(str(exc))
    else:
        st.error(f"Une erreur inattendue s'est produite : {str(exc)[:200]}")


# -- session -----------------------------------------------------------------------------------
def utilisateur() -> dict | None:
    return st.session_state.get("utilisateur")


def est_admin() -> bool:
    u = utilisateur()
    return bool(u and u.get("role") == "admin")


def barre_laterale_session() -> None:
    u = utilisateur()
    with st.sidebar:
        st.divider()
        if u:
            st.markdown(f"👤 **{u['nom']}**  \nRôle : `{u['role']}`" + ("" if u["role"] == "admin" else " (lecture seule)"))
            if st.button("Se déconnecter", key="deconnexion"):
                st.session_state.pop("utilisateur", None)
                st.rerun()
        else:
            st.caption("Vous n'êtes pas connecté·e.")


def formulaire_connexion() -> None:
    """Formulaire d'identification : e-mail d'un utilisateur de l'ontologie + mot de passe du rôle."""
    comptes = auth.liste_comptes(get_store())
    with st.form("connexion"):
        choix = st.selectbox("Compte", comptes, format_func=lambda c: f"{c['nom']} — {c['email']} ({c['role']})")
        mdp = st.text_input("Mot de passe", type="password", help="Mot de passe de votre rôle (voir le fichier .env).")
        if st.form_submit_button("Se connecter", type="primary"):
            u = auth.authentifier(choix["email"], mdp, get_store()) if choix else None
            if u:
                st.session_state["utilisateur"] = u
                st.rerun()
            else:
                st.error("Mot de passe incorrect.")


def exiger_connexion() -> dict:
    """Bloque la page tant que l'utilisateur n'est pas connecté."""
    initialiser()
    u = utilisateur()
    if not u:
        st.warning("Connectez-vous pour utiliser cette page.")
        formulaire_connexion()
        st.stop()
    return u


def reserve_admin() -> bool:
    """Retourne True si l'utilisateur peut modifier ; sinon affiche un message de lecture seule."""
    if est_admin():
        return True
    st.info("🔒 Votre rôle est « lecteur » : vous pouvez consulter les données mais pas les modifier.")
    return False
