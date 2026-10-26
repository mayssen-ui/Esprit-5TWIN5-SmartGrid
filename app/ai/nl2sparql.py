"""Traduction langage humain (français / anglais) -> SPARQL, avec des outils de TALN (pas de LLM) :

a) analyse linguistique spaCy (lemmes, POS, dépendances, NER, PhraseMatcher) + règles et modèles de requêtes ;
b) à défaut, rapprochement TF-IDF / similarité cosinus (scikit-learn) avec le catalogue de requêtes modèles ;
c) garde-fous : syntaxe validée par rdflib, lecture libre limitée à SELECT/ASK/CONSTRUCT,
   confirmation explicite pour tout INSERT/DELETE, nombre de résultats limité, journalisation.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.ai import guardrails, nlp
from app.ai.vocab import (PROP_VAR, Individu, classes_dans, individus_connus, normaliser, props_dans,
                          trouver_individu)
from app.errors import ForbiddenError, QueryRejected, SmartGridError, ValidationError
from app.labels import le_prop, libelle_prop, nom_classe, unite_prop
from app.services import crud
from app.sparql.schema import get_schema
from app.sparql.store import BaseStore, QueryResult, get_store

NOMBRE = r"(\d+(?:[.,]\d+)?)"
VERBES_AJOUT = r"(?:ajoute|ajouter|ajout|cree|creer|enregistre|enregistrer|insere|inserer|add|create|insert|nouveau|nouvelle)"
VERBES_SUPPR = r"(?:supprime|supprimer|efface|effacer|retire|retirer|enleve|enlever|delete|remove)"
VERBES_MODIF = r"(?:modifie|modifier|change|changer|mets|mettre|met a jour|mettre a jour|actualise|update|set)"
VERBES_LISTE = r"(?:cite|citer|liste|lister|affiche|afficher|montre|montrer|donne|donner|quels?|quelles?|list|show|which|what are|display)"
FONCTIONS = {
    "SUM": r"(?:total|totale|totaux|somme|cumul|cumule|sum|overall)",
    "AVG": r"(?:moyenne|moyen|moyenne|average|mean)",
    "MAX": r"(?:maximum|maximale|max|plus grande?|plus elevee?|plus forte?|highest|largest)",
    "MIN": r"(?:minimum|minimale|min|plus petite?|plus faible|lowest|smallest)",
}
NOMS_FONCTION = {"SUM": ("total", "totale"), "AVG": ("moyenne", "moyenne"), "MAX": ("maximum", "maximale"),
                 "MIN": ("minimum", "minimale")}
DOMAINE_PAR_DEFAUT = {
    "hasConsumption": "Building", "hasCapacity": "EnergySource", "hasPowerOutput": "EnergySource",
    "hasStorageCapacity": "EnergyStorage", "hasEfficiency": "EnergyStorage", "hasVoltage": "GridElement",
}


@dataclass
class Traduction:
    question: str
    sparql: str = ""
    explication: str = ""
    niveau: str = "aucun"            # "regles" | "similarite" | "edite" | "aucun"
    regle: str = ""
    ecriture: bool = False
    forme: str = "liste"             # liste | compte | agregat | valeur | detail | ecriture | autre
    contexte: dict[str, Any] = field(default_factory=dict)
    erreur: str | None = None

    def to_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class Ctx:
    question: str
    norm: str
    store: BaseStore
    classes: list[tuple[str, int, int]]
    props: list[tuple[str, int, int]]
    individus: list[Individu]
    individu: Individu | None
    ana: nlp.Analyse | None = None


# --------------------------------------------------------------------------------------------
# Utilitaires de génération SPARQL
# --------------------------------------------------------------------------------------------
def _plus_specifique(classes: list[str]) -> str | None:
    """Parmi des classes citées, garde la plus spécifique (une sous-classe l'emporte sur son parent)."""
    schema = get_schema()
    if not classes:
        return None
    return max(classes, key=lambda c: len(schema.ancetres(c)))


def _classe_sujet(ctx: Ctx, segment: tuple[int, int] | None = None) -> str | None:
    cls = [c for c, d, f in ctx.classes if segment is None or (d >= segment[0] and f <= segment[1])]
    return _plus_specifique(cls)


def _lignes_liste(cls: str, var: str = "element", filtre: tuple[str, str, float] | None = None) -> tuple[str, list[str]]:
    """Motif SELECT d'une liste : colonnes = nom + propriétés de données de la classe."""
    schema = get_schema()
    props = [p for p in schema.props_de(cls, "data") if p.nom != "hasName"][:6]
    sel = [f"?{var}", "?nom"]
    corps = [f"?{var} a/rdfs:subClassOf* sg:{cls} ;", "       sg:hasName ?nom ."]
    for p in props:
        v = PROP_VAR.get(p.nom, p.nom)
        sel.append(f"?{v}")
        if filtre and filtre[0] == p.nom:
            corps.append(f"?{var} sg:{p.nom} ?{v} .")
        else:
            corps.append(f"OPTIONAL {{ ?{var} sg:{p.nom} ?{v} }}")
    if filtre:
        prop, op, valeur = filtre
        v = PROP_VAR.get(prop, prop)
        if prop not in {p.nom for p in props}:
            sel.append(f"?{v}")
            corps.append(f"?{var} sg:{prop} ?{v} .")
        corps.append(f"FILTER(?{v} {op} {valeur:g})")
    return "\n  ".join(corps), sel


def _select_liste(cls: str, filtre=None) -> str:
    corps, sel = _lignes_liste(cls, filtre=filtre)
    return f"SELECT {' '.join(sel)}\nWHERE {{\n  {corps}\n}}\nORDER BY ?nom"


def _nombre(texte: str) -> float:
    return float(texte.replace(",", "."))


def _filtre_numerique(ctx: Ctx) -> tuple[str, str, float] | None:
    """Détecte « consommation supérieure à 5 », « plus de 10 MW », « moins de 2 »…"""
    ops = {
        r"(?:superieure?s?|depasse(?:nt)?|plus de|plus grande? que|au dessus de|greater than|more than|above|over|>)": ">",
        r"(?:inferieure?s?|moins de|plus petite? que|au dessous de|en dessous de|less than|below|under|<)": "<",
    }
    for motif, op in ops.items():
        m = re.search(rf"{motif}\s*(?:a|de|que|than|to)?\s*{NOMBRE}", ctx.norm)
        if m:
            prop = None
            for p, d, f in ctx.props:
                if d < m.start():
                    prop = p
            if prop is None and ctx.props:
                prop = ctx.props[0][0]
            if prop is None:
                prop = "hasConsumption" if "consomm" in ctx.norm else None
            if prop:
                return prop, op, _nombre(m.group(m.lastindex))
    return None


def _formate(v: Any) -> str:
    if isinstance(v, float):
        return f"{v:.3f}".rstrip("0").rstrip(".")
    return str(v)


# --------------------------------------------------------------------------------------------
# Règles d'écriture
# --------------------------------------------------------------------------------------------
def _extraire_nom(ctx: Ctx) -> str | None:
    q = ctx.question
    m = re.search(r"[«\"“]\s*(.+?)\s*[»\"”]", q)
    if m:
        return m.group(1).strip()
    m = re.search(r"(?:nomm[ée]e?s?|appel+[ée]e?s?|intitul[ée]e?s?|named|called)\s+(.+)$", q, re.IGNORECASE)
    if not m:
        return None
    reste = m.group(1)
    coupe = re.search(
        r"\s+(?:de|d'|d’|avec|ayant|dont|with|of|situ[ée]e?|localis[ée]e?|à|a|en|pour|et)\s*(?:la\s+|le\s+|l'|l’|une?\s+)?"
        r"(?:capacit|puissance|consommation|efficacit|rendement|tension|localisation|lieu|capacity|power|efficiency|"
        r"voltage|location|stockage|e-?mail|r[ôo]le|\d)", reste, re.IGNORECASE)
    if coupe:
        reste = reste[:coupe.start()]
    nom = reste.strip(" .,;?!")
    return nom or None


def _valeurs_apres_props(ctx: Ctx, classe: str, depart: int = 0) -> dict[str, Any]:
    """Lit les couples (propriété, valeur) de la phrase : « de capacité 12 », « efficacité 90 % »…"""
    donnees: dict[str, Any] = {}
    schema = get_schema()
    for prop, d, f in ctx.props:
        if d < depart:
            continue
        suite = ctx.norm[f:]
        if prop == "hasLocation":
            m = re.match(r"\s*(?:de|d|a|=|:|est|a)?\s*([a-z][a-z ]*?)\s*(?:$|,| et | avec )", suite)
            if m:
                bout = ctx.question[f + (m.start(1)):f + m.end(1)].strip()
                donnees["hasLocation"] = bout.capitalize()
            continue
        if prop == "hasEmail":
            m = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", ctx.question[f:])
            if m:
                donnees["hasEmail"] = m.group(0)
            continue
        m = re.match(rf"\s*(?:de|d|egale?|egal a|=|:|of|est|a|vaut|environ)?\s*{NOMBRE}\s*(%)?", suite)
        if not m:
            continue
        valeur = _nombre(m.group(1))
        if m.group(2) or (prop == "hasEfficiency" and 2 <= valeur <= 100):
            valeur = valeur / 100
        if prop == "hasCapacity" and schema.est_sous_classe(classe, "EnergyStorage"):
            prop = "hasStorageCapacity"
        if prop == "hasPowerOutput" and not schema.est_sous_classe(classe, "EnergySource"):
            continue
        donnees[prop] = valeur
    return donnees


def regle_ajout(ctx: Ctx) -> Traduction | None:
    if not (ctx.ana.a(*("ajouter", "creer", "enregistrer", "inserer", "add", "create", "insert", "nouveau", "nouvelle", "ajoute", "cree")) or re.search(rf"(?<![a-z]){VERBES_AJOUT}(?![a-z])", ctx.norm)):
        return None
    classe = _classe_sujet(ctx)
    if not classe:
        return Traduction(ctx.question, niveau="regles", regle="ajout", ecriture=True,
                          erreur="Précisez ce que vous voulez ajouter : un bâtiment, une batterie, une source, un nœud…")
    nom = _extraire_nom(ctx)
    if not nom:
        return Traduction(ctx.question, niveau="regles", regle="ajout", ecriture=True,
                          erreur=f"Indiquez le nom du nouvel élément, par exemple : « Ajouter {nom_classe(classe)} nommé(e) Mon nom »." )
    debut_nom = ctx.question.lower().find(nom.lower())
    donnees: dict[str, Any] = {"hasName": nom, **_valeurs_apres_props(ctx, classe, max(0, debut_nom + len(nom)))}
    t = Traduction(ctx.question, niveau="regles", regle="ajout", ecriture=True, forme="ecriture")
    try:
        _, propre, requete = crud.preparer_creation(classe, donnees, store=ctx.store)
    except (ValidationError, SmartGridError) as exc:
        t.erreur = str(exc)
        return t
    detail = ", ".join(f"{libelle_prop(p).lower()} = {_formate(float(v)) if not isinstance(v, (str, list)) else v}"
                       for p, v in propre.items() if p != "hasName")
    t.sparql = requete
    t.explication = f"Ajouter {_art(classe)} {nom_classe(classe)} nommé(e) « {nom} »" + (f" ({detail})" if detail else "") + "."
    t.contexte = {"classe": classe, "nom": nom}
    return t


def _art(cls: str) -> str:
    return "une" if nom_classe(cls).split()[0] in ("batterie", "source", "énergie") or cls in ("Substation",) else "un"


def regle_suppression(ctx: Ctx) -> Traduction | None:
    if not (ctx.ana.a(*("supprimer", "effacer", "retirer", "enlever", "delete", "remove", "supprime", "efface")) or re.search(rf"(?<![a-z]){VERBES_SUPPR}(?![a-z])", ctx.norm)):
        return None
    t = Traduction(ctx.question, niveau="regles", regle="suppression", ecriture=True, forme="ecriture")
    if not ctx.individu:
        t.erreur = "Je n'ai pas reconnu l'élément à supprimer. Citez son nom exact (exemple : « Supprimer le bâtiment ESPRIT »)."
        return t
    refs = crud.references_entrantes(ctx.individu.id, ctx.store)
    t.sparql = " ;\n".join(crud.operations_suppression(ctx.individu.id))
    t.explication = (f"Supprimer « {ctx.individu.nom} » ({nom_classe(ctx.individu.classe)})"
                     + (f" et retirer {len(refs)} lien(s) qui y font référence." if refs else "."))
    t.contexte = {"id": ctx.individu.id}
    return t


def regle_modification(ctx: Ctx) -> Traduction | None:
    if not (ctx.ana.a(*("modifier", "changer", "mettre", "actualiser", "update", "set", "modifie", "change", "mets")) or re.search(rf"(?<![a-z]){VERBES_MODIF}(?![a-z])", ctx.norm)) or not ctx.props:
        return None
    t = Traduction(ctx.question, niveau="regles", regle="modification", ecriture=True, forme="ecriture")
    if not ctx.individu:
        t.erreur = "Je n'ai pas reconnu l'élément à modifier. Citez son nom (exemple : « Modifier la capacité de la batterie Batterie Tunis 01 à 15 »)."
        return t
    prop = ctx.props[-1][0]
    schema = get_schema()
    if prop == "hasCapacity" and schema.est_sous_classe(ctx.individu.classe, "EnergyStorage"):
        prop = "hasStorageCapacity"
    m = re.search(rf"(?:\ba\b|\ben\b|=|\bto\b|\bvaut\b)\s*{NOMBRE}\s*(%)?", ctx.norm[ctx.props[-1][2]:])
    if not m:
        t.erreur = "Indiquez la nouvelle valeur, par exemple : « … à 15 »."
        return t
    valeur = _nombre(m.group(1)) / (100 if m.group(2) else 1)
    try:
        ops, _, nom = crud.preparer_modification(ctx.individu.id, {prop: valeur}, ctx.store)
    except SmartGridError as exc:
        t.erreur = str(exc)
        return t
    t.sparql = " ;\n".join(ops)
    t.explication = f"Modifier {le_prop(prop)} de « {nom} » : nouvelle valeur {_formate(valeur)}."
    return t


# --------------------------------------------------------------------------------------------
# Règles de lecture
# --------------------------------------------------------------------------------------------
def _terme_source(ctx: Ctx, droite: str, decalage: int) -> tuple[str, str] | None:
    """Décrit la source citée après « alimenté par » : retourne (motif SPARQL, description)."""
    if re.search(r"non renouvelable|non renewable", droite):
        return ("?source sg:produces ?energie . ?energie a/rdfs:subClassOf* sg:NonRenewableEnergy .",
                "une source d'énergie non renouvelable")
    if re.search(r"renouvelable|renewable|verte?s?\b|propre", droite):
        return ("?source sg:produces ?energie . ?energie a/rdfs:subClassOf* sg:RenewableEnergy .",
                "une source d'énergie renouvelable")
    ind = trouver_individu(droite, [i for i in ctx.individus if get_schema().est_sous_classe(i.classe, "EnergySource")])
    if ind:
        return (f"FILTER(?source = sg:{ind.id})", f"la source « {ind.nom} »")
    cls = _plus_specifique([c for c, d, f in classes_dans(droite) if get_schema().est_sous_classe(c, "EnergySource")])
    if cls:
        return (f"?source a/rdfs:subClassOf* sg:{cls} .", f"{_art(cls)} {nom_classe(cls)}")
    return None


def regle_alimentation(ctx: Ctx) -> Traduction | None:
    """« Quels bâtiments sont alimentés par une ferme solaire ? » et variantes."""
    m = re.search(r"(?:alimente(?:e|es|s)?|supplied|powered|fed)\s+(?:par|by)\s+(.+)$", ctx.norm)
    agent = nlp.complement_agent(ctx.ana)          # dépendances syntaxiques : « alimenté PAR <groupe nominal> »
    if agent:
        droite, pos = ctx.norm[agent[0]:], agent[0]
    elif m:
        droite, pos = m.group(1), m.start(1)
    else:
        droite, pos = None, len(ctx.norm)
    renouvelable_seul = re.search(r"batiments?\s+(?:renouvelables?|verts?)", ctx.norm)
    if droite is None and not renouvelable_seul:
        return None
    sujet = _classe_sujet(ctx, (0, pos)) or "Building"
    if not get_schema().est_sous_classe(sujet, "Building"):
        return None
    if droite is not None:
        terme = _terme_source(ctx, droite, pos)
        if not terme:
            return None
        motif, desc = terme
    else:
        motif, desc = ("?source sg:produces ?energie . ?energie a/rdfs:subClassOf* sg:RenewableEnergy .",
                       "une source d'énergie renouvelable")
    compter = re.search(r"combien|nombre|how many|count", ctx.norm)
    corps = (f"?batiment a/rdfs:subClassOf* sg:{sujet} ;\n            sg:hasName ?nom_batiment ;\n"
             f"            sg:suppliedBy ?source .\n  ?source sg:hasName ?nom_source .\n  {motif}")
    if compter:
        sparql = f"SELECT (COUNT(DISTINCT ?batiment) AS ?nombre)\nWHERE {{\n  {corps}\n}}"
        forme = "compte"
    else:
        sparql = f"SELECT DISTINCT ?batiment ?nom_batiment ?source ?nom_source\nWHERE {{\n  {corps}\n}}\nORDER BY ?nom_batiment"
        forme = "liste"
    return Traduction(ctx.question, sparql, f"{'Compter' if compter else 'Citer'} les {nom_classe(sujet, True)} alimentés par {desc}.",
                      "regles", "alimentation", False, forme, {"classe": sujet, "colonne_nom": "nom_batiment"})


def regle_batterie(ctx: Ctx) -> Traduction | None:
    if not re.search(r"(?:possede|possedent|ont|avec|equipe|dote|disposent|have|has|with)\b.*\b(?:batteri|stockage|storage|battery)", ctx.norm):
        return None
    sujet = _classe_sujet(ctx, (0, ctx.norm.find("batteri") if "batteri" in ctx.norm else len(ctx.norm))) or "Building"
    if not get_schema().est_sous_classe(sujet, "Building"):
        sujet = "Building"
    sparql = f"""SELECT ?nom_batiment ?nom_batterie ?capacite_stockage ?efficacite
WHERE {{
  ?batiment a/rdfs:subClassOf* sg:{sujet} ;
            sg:hasName ?nom_batiment ;
            sg:hasStorage ?batterie .
  ?batterie sg:hasName ?nom_batterie .
  OPTIONAL {{ ?batterie sg:hasStorageCapacity ?capacite_stockage }}
  OPTIONAL {{ ?batterie sg:hasEfficiency ?efficacite }}
}}
ORDER BY ?nom_batiment"""
    return Traduction(ctx.question, sparql, f"Citer les {nom_classe(sujet, True)} qui possèdent une batterie.",
                      "regles", "batterie", False, "liste", {"classe": sujet, "colonne_nom": "nom_batiment"})


def regle_proprietaires(ctx: Ctx) -> Traduction | None:
    if not re.search(r"utilisateurs?|users?|proprietaires?|owners?", ctx.norm):
        return None
    if not re.search(r"possede|possedent|proprietaire|owns?|gere|gerent|manages?|batiment|noeud|usine|maison", ctx.norm):
        return None
    gere = re.search(r"(?:gere|gerent|manage|gestionnaire)", ctx.norm) is not None
    cls_cible = None
    for c, d, f in ctx.classes:
        if c != "User":
            cls_cible = c
    if gere:
        cible = cls_cible if cls_cible and get_schema().est_sous_classe(cls_cible, "GridNode") else "GridNode"
        prop, titre = "manages", "gèrent des nœuds du réseau"
    else:
        cible = cls_cible if cls_cible and get_schema().est_sous_classe(cls_cible, "Building") else "Building"
        prop, titre = "owns", f"possèdent des {nom_classe(cible, True)}"
    sparql = f"""SELECT ?nom_utilisateur ?email ?nom_element
WHERE {{
  ?u a sg:User ;
     sg:hasName ?nom_utilisateur ;
     sg:{prop} ?element .
  ?element a/rdfs:subClassOf* sg:{cible} ;
           sg:hasName ?nom_element .
  OPTIONAL {{ ?u sg:hasEmail ?email }}
}}
ORDER BY ?nom_utilisateur"""
    return Traduction(ctx.question, sparql, f"Citer les utilisateurs qui {titre}.", "regles", "proprietaires",
                      False, "liste", {"classe": "User", "colonne_nom": "nom_utilisateur"})


def regle_noeuds(ctx: Ctx) -> Traduction | None:
    if re.search(r"noe?uds?|nodes?", ctx.norm) and re.search(r"connecte|reli|connected|lies?\b", ctx.norm):
        sparql = """SELECT ?nom_noeud_1 ?lieu_1 ?nom_noeud_2 ?lieu_2
WHERE {
  ?n1 sg:connectedTo ?n2 ; sg:hasName ?nom_noeud_1 .
  ?n2 sg:hasName ?nom_noeud_2 .
  OPTIONAL { ?n1 sg:hasLocation ?lieu_1 }
  OPTIONAL { ?n2 sg:hasLocation ?lieu_2 }
  FILTER(STR(?n1) < STR(?n2))
}"""
        return Traduction(ctx.question, sparql, "Citer les nœuds connectés entre eux avec leur localisation.",
                          "regles", "noeuds_connectes", False, "liste", {"colonne_nom": "nom_noeud_1"})
    if re.search(r"sources?", ctx.norm) and re.search(r"noe?uds?|nodes?", ctx.norm) \
            and re.search(r"alimente|hasSource|reli|connecte|fournit|alimentent", ctx.norm):
        sparql = """SELECT ?nom_noeud ?nom_source ?puissance_produite
WHERE {
  ?n a sg:GridNode ; sg:hasName ?nom_noeud ; sg:hasSource ?s .
  ?s sg:hasName ?nom_source .
  OPTIONAL { ?s sg:hasPowerOutput ?puissance_produite }
}
ORDER BY ?nom_noeud"""
        return Traduction(ctx.question, sparql, "Citer les nœuds du réseau et les sources qui les alimentent.",
                          "regles", "noeuds_sources", False, "liste", {"colonne_nom": "nom_noeud"})
    if re.search(r"postes?|substations?", ctx.norm) and re.search(r"noe?uds?|nodes?", ctx.norm):
        sparql = """SELECT ?nom_poste ?tension_poste ?nom_noeud
WHERE {
  ?p a sg:Substation ; sg:hasName ?nom_poste ; sg:contains ?n .
  ?n sg:hasName ?nom_noeud .
  OPTIONAL { ?p sg:hasVoltage ?tension_poste }
}
ORDER BY ?nom_poste"""
        return Traduction(ctx.question, sparql, "Citer les postes électriques et les nœuds qu'ils contiennent.",
                          "regles", "postes_noeuds", False, "liste", {"colonne_nom": "nom_poste"})
    return None


def regle_agregat(ctx: Ctx) -> Traduction | None:
    fonction = next((f for f, motif in FONCTIONS.items() if re.search(rf"(?<![a-z]){motif}(?![a-z])", ctx.norm)), None)
    if not fonction or not ctx.props:
        return None
    prop = ctx.props[0][0]
    cls = _classe_sujet(ctx) or DOMAINE_PAR_DEFAUT.get(prop, "Thing")
    if prop == "hasCapacity" and get_schema().est_sous_classe(cls, "EnergyStorage"):
        prop = "hasStorageCapacity"
    var = NOMS_FONCTION[fonction][0]
    sparql = (f"SELECT ({fonction}(?valeur) AS ?{var}) (COUNT(?element) AS ?nombre)\nWHERE {{\n"
              f"  ?element a/rdfs:subClassOf* sg:{cls} ;\n           sg:{prop} ?valeur .\n}}")
    expl = f"Calculer {le_prop(prop)} {NOMS_FONCTION[fonction][1]} des {nom_classe(cls, True)}."
    return Traduction(ctx.question, sparql, expl, "regles", "agregat", False, "agregat",
                      {"classe": cls, "prop": prop, "fonction": fonction, "var": var})


def regle_top(ctx: Ctx) -> Traduction | None:
    m = re.search(rf"(?:\btop\b\s*{NOMBRE}?|{NOMBRE}\s+plus\s+(?:gros|grands?|importants?|eleves?|forts?)|plus\s+(?:gros|grands?)\s+consommateurs?)", ctx.norm)
    if not m or re.search(r"moyenne|total", ctx.norm):
        return None
    n = next((g for g in m.groups() if g), None)
    n = int(float(n.replace(",", "."))) if n else 5
    prop = ctx.props[0][0] if ctx.props else ("hasConsumption" if "consommateur" in ctx.norm else None)
    if not prop:
        return None
    cls = _classe_sujet(ctx) or DOMAINE_PAR_DEFAUT.get(prop, "Thing")
    ordre = "ASC" if re.search(r"plus (?:petit|faible)|moins", ctx.norm) else "DESC"
    sparql = (f"SELECT ?nom ?valeur\nWHERE {{\n  ?element a/rdfs:subClassOf* sg:{cls} ;\n           sg:hasName ?nom ;\n"
              f"           sg:{prop} ?valeur .\n}}\nORDER BY {ordre}(?valeur)\nLIMIT {n}")
    return Traduction(ctx.question, sparql, f"Citer les {n} {nom_classe(cls, True)} avec {le_prop(prop)} la plus "
                      f"{'élevée' if ordre == 'DESC' else 'faible'}.", "regles", "top", False, "liste", {"colonne_nom": "nom"})


def regle_comptage(ctx: Ctx) -> Traduction | None:
    if not re.search(r"combien|nombre d|how many|count|number of", ctx.norm):
        return None
    cls = _classe_sujet(ctx)
    if not cls:
        return None
    filtre = _filtre_numerique(ctx)
    corps, _ = _lignes_liste(cls, filtre=filtre)
    sparql = f"SELECT (COUNT(DISTINCT ?element) AS ?nombre)\nWHERE {{\n  {corps}\n}}"
    return Traduction(ctx.question, sparql, f"Compter les {nom_classe(cls, True)}.", "regles", "comptage", False,
                      "compte", {"classe": cls})


def regle_valeur(ctx: Ctx) -> Traduction | None:
    if not ctx.individu or not ctx.props:
        return None
    prop = ctx.props[0][0]
    if prop == "hasCapacity" and get_schema().est_sous_classe(ctx.individu.classe, "EnergyStorage"):
        prop = "hasStorageCapacity"
    sparql = f"SELECT ?valeur\nWHERE {{\n  sg:{ctx.individu.id} sg:{prop} ?valeur .\n}}"
    return Traduction(ctx.question, sparql, f"Lire {le_prop(prop)} de « {ctx.individu.nom} ».",
                      "regles", "valeur", False, "valeur", {"prop": prop, "nom": ctx.individu.nom})


def regle_detail(ctx: Ctx) -> Traduction | None:
    if not ctx.individu:
        return None
    if not re.search(r"detail|information|infos?|fiche|decris|decrire|parle|presente|tout sur|everything|about|describe|que sais", ctx.norm) \
            and len(ctx.norm.split()) > 6:
        return None
    sparql = (f"SELECT ?propriete ?valeur\nWHERE {{\n  sg:{ctx.individu.id} ?propriete ?valeur .\n"
              "  FILTER(?propriete != rdf:type)\n}\nORDER BY ?propriete")
    return Traduction(ctx.question, sparql, f"Afficher toutes les informations sur « {ctx.individu.nom} ».",
                      "regles", "detail", False, "detail", {"nom": ctx.individu.nom})


def regle_liste(ctx: Ctx) -> Traduction | None:
    cls = _classe_sujet(ctx)
    if not cls:
        return None
    if not (ctx.ana.a(*("citer", "lister", "afficher", "montrer", "donner", "quel", "list", "show", "which", "display", "cite", "liste")) or re.search(VERBES_LISTE, ctx.norm)) and len(ctx.norm.split()) > 5 and not _filtre_numerique(ctx):
        return None
    filtre = _filtre_numerique(ctx)
    sparql = _select_liste(cls, filtre)
    expl = f"Citer {'les ' + nom_classe(cls, True)}"
    if filtre:
        expl += f" dont {le_prop(filtre[0])} est {'supérieure' if filtre[1] == '>' else 'inférieure'} à {filtre[2]:g}"
    return Traduction(ctx.question, sparql, expl + ".", "regles", "liste", False, "liste",
                      {"classe": cls, "colonne_nom": "nom"})


REGLES = [regle_ajout, regle_suppression, regle_modification, regle_alimentation, regle_top, regle_agregat,
          regle_comptage, regle_valeur, regle_batterie, regle_proprietaires, regle_noeuds, regle_detail, regle_liste]


# --------------------------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------------------------
# Formulations alternatives (langage courant) ajoutées aux phrases modèles pour la similarité TF-IDF
ALIAS = {
    "bilan_par_noeud": "bilan excédent déficit équilibre production consommation chaque zone endroit secteur réseau",
    "batiments_sans_source": "bâtiments non alimentés sans alimentation électrique privés de courant sans source",
    "conso_superieure_production": "bâtiments qui consomment trop plus que leur source ne produit surcharge déficit",
    "noeuds_atteignables": "quels noeuds peut-on atteindre joindre depuis un point en suivant les connexions chemin",
    "sources_plusieurs_batiments": "sources qui alimentent plusieurs bâtiments au moins deux regroupées",
    "batiments_au_dessus_moyenne": "gros consommateurs consomment plus que la moyenne supérieur à la moyenne",
    "batiments_batteries": "bâtiments équipés de stockage batterie capacité efficacité",
}
_SIMILARITE: "nlp.Similarite | None" = None


def _similarite() -> "nlp.Similarite":
    """Index TF-IDF des phrases modèles : libellés et explications du catalogue de requêtes croisées."""
    global _SIMILARITE
    if _SIMILARITE is None:
        from app.sparql.queries import CATALOGUE
        _SIMILARITE = nlp.Similarite([(q.id, f"{q.libelle}. {q.explication} {ALIAS.get(q.id, '')}") for q in CATALOGUE])
    return _SIMILARITE


def traduire(question: str, store: BaseStore | None = None) -> Traduction:
    """Niveau a) analyse spaCy + règles, puis niveau b) similarité TF-IDF avec le catalogue de requêtes ;
    le niveau c) (garde-fous) s'applique dans `repondre`."""
    store = store or get_store()
    question = (question or "").strip()
    if not question:
        return Traduction(question, erreur="Posez une question en français ou en anglais.")
    norm = normaliser(question)
    ana = nlp.analyser(question)
    individus = individus_connus(store)
    ctx = Ctx(question, norm, store, classes_dans(ana), props_dans(ana), individus,
              trouver_individu(question, individus), ana)
    for regle in REGLES:
        try:
            t = regle(ctx)
        except SmartGridError as exc:
            t = Traduction(question, niveau="regles", regle=regle.__name__, erreur=str(exc))
        if t is not None:
            return t
    from app.sparql.queries import PAR_ID
    trouve = _similarite().meilleur(question)
    if trouve:
        q = PAR_ID[trouve[0]]
        return Traduction(question, q.sparql, f"{q.libelle}. (requête modèle la plus proche, similarité {trouve[1]:.0%})",
                          "similarite", q.id, False, "liste", {"similarite": trouve[1]})
    return Traduction(question, erreur="Je n'ai pas compris cette question. Essayez par exemple : « Citer les différents bâtiments ».")


def phrase_resultat(t: Traduction, res: QueryResult | None) -> str:
    """Explication en langage naturel du résultat obtenu."""
    if res is None:
        return t.explication
    if res.kind == "ask":
        return "Oui." if res.boolean else "Non."
    n = len(res.rows)
    cls = t.contexte.get("classe")
    if t.forme == "compte" and res.rows:
        nb = int(res.rows[0].get("nombre") or 0)
        pluriel = nom_classe(cls, nb > 1) if cls else "élément(s)"
        return f"Il y a {nb} {pluriel}." if nb != 1 else f"Il y a 1 {pluriel}."
    if t.forme == "agregat" and res.rows:
        v = res.rows[0].get(t.contexte["var"])
        if v is None:
            return "Aucune valeur trouvée pour ce calcul."
        u = unite_prop(t.contexte["prop"])
        f = t.contexte["fonction"]
        return (f"{le_prop(t.contexte['prop']).capitalize()} {NOMS_FONCTION[f][1]} des {nom_classe(t.contexte['classe'], True)} "
                f"est de {_formate(v)}{' ' + u if u else ''} (sur {res.rows[0].get('nombre')} élément(s)).")
    if t.forme == "valeur":
        if not res.rows:
            return f"Aucune valeur n'est renseignée pour « {t.contexte['nom']} » ({le_prop(t.contexte['prop'])})."
        u = unite_prop(t.contexte["prop"])
        return f"{le_prop(t.contexte['prop']).capitalize()} de « {t.contexte['nom']} » est de {_formate(res.rows[0]['valeur'])}{' ' + u if u else ''}."
    if n == 0:
        return "Aucun résultat ne correspond à cette demande."
    col = t.contexte.get("colonne_nom") or next((v for v in res.vars if v.startswith("nom")), res.vars[0] if res.vars else None)
    noms = [str(r.get(col)) for r in res.rows if col and r.get(col) is not None]
    noms = list(dict.fromkeys(noms))
    extrait = ", ".join(noms[:8]) + ("…" if len(noms) > 8 else "")
    return f"J'ai trouvé {n} résultat(s)" + (f" : {extrait}." if extrait and t.forme != "detail" else ".")


def repondre(
    question: str = "", confirmer: bool = False, sparql: str | None = None, store: BaseStore | None = None,
    peut_ecrire: bool = True, utilisateur: str | None = None,
) -> dict:
    """Point d'entrée unique : traduit, valide (garde-fous), exécute et explique.

    - `sparql` : requête corrigée à la main par l'utilisateur (bouton « Corriger la requête »).
    - `confirmer` : obligatoire pour exécuter un INSERT / DELETE.
    """
    store = store or get_store()
    if sparql and sparql.strip():
        t = Traduction(question, sparql.strip(), "Requête saisie ou corrigée à la main.", "edite", "manuel")
    else:
        t = traduire(question, store)
    sortie: dict[str, Any] = {
        "question": question, "sparql": t.sparql, "explication": t.explication, "niveau": t.niveau,
        "regle": t.regle, "resultat": None, "execute": False, "confirmation_requise": False,
        "tronque": False, "message": "", "erreur": t.erreur,
    }
    if t.erreur or not t.sparql:
        sortie["erreur"] = t.erreur or "Aucune requête n'a pu être produite."
        guardrails.journaliser({"question": question, "niveau": t.niveau, "sparql": t.sparql, "erreur": sortie["erreur"],
                                "utilisateur": utilisateur})
        return sortie
    try:
        analyse = guardrails.analyser(t.sparql)
    except QueryRejected as exc:
        sortie["erreur"] = str(exc)
        guardrails.journaliser({"question": question, "niveau": t.niveau, "sparql": t.sparql, "erreur": str(exc),
                                "utilisateur": utilisateur})
        return sortie
    sortie["sparql"] = analyse.requete
    sortie["tronque"] = analyse.limitee
    try:
        if analyse.type == "update":
            sortie["confirmation_requise"] = True
            if not peut_ecrire:
                raise ForbiddenError("Votre rôle (lecteur) ne permet pas de modifier les données.")
            if not confirmer:
                sortie["message"] = "Cette demande modifie les données. Relisez la requête puis confirmez pour l'exécuter."
            else:
                store.update(analyse.requete)
                sortie.update(execute=True, confirmation_requise=False, message="La modification a été enregistrée.")
        else:
            res = store.query(analyse.requete)
            if len(res.rows) > guardrails.settings.max_results:
                res.rows = res.rows[:guardrails.settings.max_results]
                sortie["tronque"] = True
            sortie["resultat"] = res.to_dict()
            sortie["execute"] = True
            sortie["message"] = phrase_resultat(t, res)
    except (SmartGridError, Exception) as exc:  # erreurs d'exécution : message lisible
        sortie["erreur"] = str(exc) if isinstance(exc, SmartGridError) else f"La requête n'a pas pu être exécutée : {str(exc)[:200]}"
    guardrails.journaliser({"question": question, "niveau": t.niveau, "regle": t.regle, "sparql": sortie["sparql"],
                            "execute": sortie["execute"], "erreur": sortie["erreur"], "utilisateur": utilisateur})
    return sortie
