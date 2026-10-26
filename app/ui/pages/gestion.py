"""CRUD complet : consulter, ajouter, modifier, supprimer les éléments de chaque catégorie."""
import datetime as dt

import pandas as pd
import streamlit as st

from app.errors import IntegrityError, SmartGridError
from app.labels import libelle_avec_unite, nom_classe
from app.ui import backend as crud
from app.sparql.schema import get_schema
from app.sparql.store import get_store
from app.ui import common

common.exiger_connexion()
store = get_store()
schema = get_schema()

st.title("🗂️ Gérer les éléments du réseau")

CATEGORIES = ["Building", "EnergySource", "EnergyStorage", "GridElement", "Energy", "User"]
col1, col2 = st.columns([2, 3])
racine = col1.selectbox("Catégorie", CATEGORIES, format_func=lambda c: nom_classe(c, True).capitalize())
sous = [c for c in schema.descendants(racine) if not schema.classes[c]["definie"]]
cls = col2.selectbox(
    "Type précis", sous, format_func=lambda c: "Tous les types" if c == racine else nom_classe(c, True).capitalize(),
    help="Choisissez un type précis (par exemple « bâtiments industriels ») ou laissez « Tous les types ».")

onglets = st.tabs(["📋 Consulter", "➕ Ajouter", "✏️ Modifier", "🗑️ Supprimer"])


# ---------------------------------------------------------------------------- champs de formulaire
def widget_champ(c: dict, cle: str, valeur=None):
    """Crée le champ de saisie adapté au type de la propriété et retourne la valeur saisie."""
    label = libelle_avec_unite(c["nom"]) + (" *" if c["required"] else "")
    kind = c["kind"]
    if kind == "object":
        options = c["options"]
        if c["multi"]:
            return st.multiselect(label, options, default=[v for v in (valeur or []) if v in options], key=cle)
        liste = [""] + options
        defaut = liste.index(valeur) if valeur in liste else 0
        return st.selectbox(label, liste, index=defaut, key=cle, format_func=lambda x: "(aucun)" if x == "" else x)
    if kind == "choice":
        options = c["options"]
        return st.selectbox(label, options, index=options.index(valeur) if valeur in options else 0, key=cle)
    if kind == "dateTime":
        defaut = None
        if valeur:
            try:
                defaut = dt.datetime.fromisoformat(str(valeur)).date()
            except ValueError:
                defaut = None
        d = st.date_input(label, value=defaut, key=cle, format="YYYY-MM-DD")
        return d.isoformat() if d else ""
    aide = None
    if "min" in c:
        aide = "Nombre " + ("strictement positif" if c.get("min_strict") else "positif ou nul") + (
            f", au plus {c['max']}" if c.get("max") is not None else "")
    return st.text_input(label, value="" if valeur is None else str(valeur), key=cle, help=aide)


# ---------------------------------------------------------------------------- consulter
with onglets[0]:
    common.phrase(f"Lister {'tous les ' if cls == racine else 'toutes les '}{nom_classe(cls, True)}.")
    c1, c2, c3, c4 = st.columns([3, 2, 2, 1])
    texte = c1.text_input("Rechercher", placeholder="Un nom, un lieu, une valeur…", key="rech")
    donnees_brutes = crud.rechercher(cls, taille=100000, store=store)
    colonnes = donnees_brutes["colonnes"]
    types = ["(tous)"] + sorted({l["type"] for l in donnees_brutes["lignes"]})
    filtre_type = c2.selectbox("Filtrer par type", types, key="ftype")
    tri = c3.selectbox("Trier par", colonnes, key="tri")
    decroissant = c4.checkbox("Décroissant", key="dec")
    taille = st.select_slider("Éléments par page", [5, 10, 20, 50], value=10, key="taille")
    res = crud.rechercher(cls, texte, {"type": filtre_type}, tri, decroissant, st.session_state.get("page_n", 1), taille, store)
    page = st.number_input(f"Page (sur {res['pages']})", 1, res["pages"], min(st.session_state.get("page_n", 1), res["pages"]), key="page_n")
    if page != res["page"]:
        res = crud.rechercher(cls, texte, {"type": filtre_type}, tri, decroissant, int(page), taille, store)
    st.caption(f"{res['total']} élément(s) trouvé(s).")
    common.tableau(pd.DataFrame(res["lignes"]))
    common.voir_sparql(crud.requete_liste(cls))

    st.subheader("Fiche détail")
    ids = [i["id"] for i in crud.lister_ids(cls, store)]
    if ids:
        choisi = st.selectbox("Choisir un élément", ids, key="fiche_id")
        f = crud.fiche(choisi, store)
        common.phrase(f"Afficher toutes les informations et les liens de « {f['nom']} ».")
        st.markdown(f"### {f['nom']}  \n`{f['id']}` · {nom_classe(f['type'])}")
        g1, g2 = st.columns(2)
        with g1:
            st.markdown("**Caractéristiques**")
            from app.labels import libelle_prop
            common.tableau([{"Propriété": libelle_avec_unite(p), "Valeur": v} for p, v in f["donnees"].items()])
        with g2:
            st.markdown("**Liens sortants**")
            common.tableau([{"Lien": libelle_prop(p), "Élément": ", ".join(x["nom"] for x in vs)} for p, vs in f["relations"].items()])
            st.markdown("**Liens entrants** (éléments qui s'y réfèrent)")
            common.tableau([{"Élément": r["nom"], "Lien": libelle_prop(r["propriete"])} for r in f["references"]])
        common.voir_sparql(f"SELECT ?propriete ?valeur WHERE {{ sg:{f['id']} ?propriete ?valeur }}")

# ---------------------------------------------------------------------------- ajouter
with onglets[1]:
    if common.reserve_admin():
        type_cree = st.selectbox("Que voulez-vous ajouter ?", sous, index=1 if len(sous) > 1 else 0,
                                 format_func=lambda c: nom_classe(c).capitalize(), key="type_cree")
        common.phrase(f"Ajouter un nouvel élément de type « {nom_classe(type_cree)} ».")
        champs = crud.champs_formulaire(type_cree, store)
        with st.form(f"ajout_{type_cree}", clear_on_submit=False):
            saisie = {c["nom"]: widget_champ(c, f"add_{type_cree}_{c['nom']}") for c in champs}
            identifiant = st.text_input("Identifiant technique (facultatif)", help="Laissez vide pour le générer à partir du nom.",
                                        key=f"id_{type_cree}")
            ok = st.form_submit_button(f"Ajouter {nom_classe(type_cree)}", type="primary")
        if ok:
            try:
                op = crud.creer(type_cree, saisie, identifiant or None, store)
                st.success(op.message)
                common.voir_sparql(op.sparql)
            except SmartGridError as exc:
                common.erreur(exc)

# ---------------------------------------------------------------------------- modifier
with onglets[2]:
    if common.reserve_admin():
        ids = [i["id"] for i in crud.lister_ids(cls, store)]
        if not ids:
            st.info("Aucun élément à modifier.")
        else:
            cible = st.selectbox("Élément à modifier", ids, key="mod_id")
            f = crud.fiche(cible, store)
            common.phrase(f"Modifier les informations de « {f['nom']} » (valeurs actuelles préremplies).")
            actuel = {**f["donnees"], **{p: ([x["id"] for x in v] if len(v) > 1 or p not in crud.MONO_VALUEES else v[0]["id"])
                                         for p, v in f["relations"].items()}}
            champs = crud.champs_formulaire(f["type"], store)
            with st.form(f"modif_{cible}"):
                saisie = {c["nom"]: widget_champ(c, f"mod_{cible}_{c['nom']}", actuel.get(c["nom"])) for c in champs}
                ok = st.form_submit_button("Enregistrer les modifications", type="primary")
            if ok:
                changes = {}
                for k, v in saisie.items():
                    ancien = actuel.get(k)
                    if isinstance(v, list) or isinstance(ancien, list):
                        if sorted(v if isinstance(v, list) else [v]) != sorted(ancien if isinstance(ancien, list) else [ancien]):
                            changes[k] = v
                        continue
                    if v in ("", None) and ancien in (None, ""):
                        continue
                    try:
                        if float(str(v).replace(",", ".")) == float(ancien):
                            continue
                    except (TypeError, ValueError):
                        pass
                    if str(ancien or "").startswith(str(v)) and len(str(v)) == 10:
                        continue                                   # même date, heure ignorée
                    if str(v) != str(ancien if ancien is not None else ""):
                        changes[k] = v
                try:
                    op = crud.modifier(cible, changes, store)
                    st.success(op.message)
                    common.voir_sparql(op.sparql)
                except SmartGridError as exc:
                    common.erreur(exc)

# ---------------------------------------------------------------------------- supprimer
with onglets[3]:
    if common.reserve_admin():
        ids = [i["id"] for i in crud.lister_ids(cls, store)]
        if not ids:
            st.info("Aucun élément à supprimer.")
        else:
            cible = st.selectbox("Élément à supprimer", ids, key="sup_id")
            f = crud.fiche(cible, store)
            common.phrase(f"Supprimer « {f['nom']} » ({nom_classe(f['type'])}).")
            refs = f["references"]
            cascade = False
            if refs:
                from app.labels import libelle_prop
                st.warning(f"⚠️ « {f['nom']} » est utilisé par {len(refs)} lien(s) :")
                common.tableau([{"Élément": r["nom"], "Lien": libelle_prop(r["propriete"])} for r in refs])
                cascade = st.checkbox("Supprimer aussi ces liens (suppression en cascade)", key="cascade")
            confirme = st.checkbox("Oui, je confirme la suppression définitive de cet élément", key="confirme_sup")
            if st.button("Supprimer", type="primary", disabled=not confirme):
                try:
                    op = crud.supprimer(cible, cascade, store)
                    st.success(op.message)
                    common.voir_sparql(op.sparql)
                except IntegrityError as exc:
                    common.erreur(exc)
                except SmartGridError as exc:
                    common.erreur(exc)
