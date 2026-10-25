"""CRUD complet sur les individus de l'ontologie, via SPARQL 1.1 Query et Update.

Tous les formulaires sont générés dynamiquement depuis le schéma (propriétés applicables à la
classe, listes déroulantes alimentées par les individus existants).
"""
from __future__ import annotations

import datetime as dt
import re
from decimal import Decimal, InvalidOperation
from typing import Any

from app.errors import IntegrityError, NotFoundError, ValidationError
from app.labels import OBLIGATOIRES, REGLES_NUM, ROLES, libelle_prop, nom_classe
from app.services.common import ID_VALIDE, Op, sans_accents, slug
from app.sparql.prefixes import esc_literal
from app.sparql.schema import Prop, get_schema
from app.sparql.store import BaseStore, get_store

# Propriétés d'objet qui n'acceptent qu'une seule valeur
MONO_VALUEES = {"suppliedBy", "locatedIn", "consumes", "produces", "storesEnergy"}
RDF_TYPE_SUFFIX = "rdf-syntax-ns#type"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# --------------------------------------------------------------------------------------------
# Schéma des formulaires
# --------------------------------------------------------------------------------------------
def resoudre_classe(nom: str) -> str:
    """Retrouve le nom exact d'une classe (insensible à la casse) ; erreur claire sinon."""
    schema = get_schema()
    for c in schema.classes:
        if c.lower() == nom.lower():
            return c
    raise NotFoundError(
        f"La catégorie « {nom} » n'existe pas. Catégories disponibles : {', '.join(sorted(schema.classes))}."
    )


def champs_formulaire(cls: str, store: BaseStore | None = None) -> list[dict]:
    """Description des champs d'un formulaire pour la classe `cls`."""
    store = store or get_store()
    schema = get_schema()
    champs = []
    for p in sorted(schema.props_de(cls), key=lambda x: (x.type == "object", x.nom != "hasName", x.nom)):
        if p.nom == "hasName":
            ordre = 0
        champ: dict[str, Any] = {
            "nom": p.nom, "label": libelle_prop(p.nom), "required": p.nom in OBLIGATOIRES,
            "kind": "object" if p.type == "object" else p.portee[0].replace("xsd:", "") if p.portee else "string",
            "multi": p.type == "object" and p.nom not in MONO_VALUEES,
        }
        if p.nom == "hasRole":
            champ["kind"] = "choice"
            champ["options"] = ROLES
        if p.type == "object":
            options: list[str] = []
            for portee in p.portee:
                options += [i["id"] for i in lister_ids(portee, store)]
            champ["options"] = sorted(set(options))
            champ["portee"] = p.portee
        if p.nom in REGLES_NUM:
            champ["min"], champ["min_strict"], champ["max"] = REGLES_NUM[p.nom]
        champs.append(champ)
    return champs


def lister_ids(cls: str, store: BaseStore | None = None) -> list[dict]:
    """Identifiants et noms de tous les individus d'une classe (sous-classes comprises)."""
    store = store or get_store()
    q = f"""SELECT DISTINCT ?id ?nom WHERE {{
  ?id a/rdfs:subClassOf* sg:{cls} .
  OPTIONAL {{ ?id sg:hasName ?nom }}
}} ORDER BY ?id"""
    return [{"id": r["id"], "nom": r["nom"] or r["id"]} for r in store.query(q).rows if isinstance(r["id"], str)]


# --------------------------------------------------------------------------------------------
# Lecture
# --------------------------------------------------------------------------------------------
def requete_liste(cls: str) -> str:
    """Requête SPARQL (affichable) qui retourne tous les individus d'une classe avec leurs valeurs."""
    return f"""SELECT ?individu ?propriete ?valeur WHERE {{
  ?individu a/rdfs:subClassOf* sg:{cls} .
  ?individu ?propriete ?valeur .
  FILTER(!(?propriete = rdf:type && ?valeur = owl:NamedIndividual))
}}"""


def _cle_prop(p: str) -> str:
    return "type" if p.endswith(RDF_TYPE_SUFFIX) else p


def _regrouper(rows: list[dict]) -> dict[str, dict]:
    """Regroupe les triplets (individu, propriété, valeur) en enregistrements."""
    schema = get_schema()
    res: dict[str, dict] = {}
    for r in rows:
        s, p, o = r["individu"], _cle_prop(r["propriete"]), r["valeur"]
        if not isinstance(s, str) or s.startswith("_:") or s.startswith("http"):
            continue
        rec = res.setdefault(s, {"id": s, "types": [], "props": {}})
        if p == "type":
            if o in schema.classes:
                rec["types"].append(o)
            continue
        pr = schema.props.get(p)
        if pr is None:
            continue
        if pr.type == "object" and p not in MONO_VALUEES or (pr.type == "object" and p in rec["props"]):
            lst = rec["props"].setdefault(p, [])
            lst.append(o)
        else:
            rec["props"][p] = o if pr.type == "data" else o
    for rec in res.values():
        rec["type"] = _plus_specifique(rec["types"])
        for p, v in rec["props"].items():
            if isinstance(v, list):
                v.sort()
    return res


def _plus_specifique(types: list[str]) -> str:
    """Parmi les types directs, retient la classe la plus profonde de la hiérarchie."""
    if not types:
        return ""
    schema = get_schema()
    return max(types, key=lambda t: len(schema.ancetres(t)))


def individus(cls: str, store: BaseStore | None = None) -> list[dict]:
    """Tous les individus d'une classe, sous forme d'enregistrements {id, type, props}."""
    store = store or get_store()
    cls = resoudre_classe(cls)
    return list(_regrouper(store.query(requete_liste(cls)).rows).values())


def _plat(rec: dict) -> dict:
    ligne = {"id": rec["id"], "type": rec["type"]}
    for p, v in rec["props"].items():
        ligne[p] = ", ".join(v) if isinstance(v, list) else v
    return ligne


def rechercher(
    cls: str, texte: str = "", filtres: dict[str, str] | None = None, tri: str | None = None,
    decroissant: bool = False, page: int = 1, taille: int = 10, store: BaseStore | None = None,
) -> dict:
    """Tableau d'individus avec recherche plein texte, filtres, tri et pagination."""
    lignes = [_plat(r) for r in individus(cls, store)]
    t = sans_accents(texte).strip()
    if t:
        lignes = [l for l in lignes if any(t in sans_accents(str(v)) for v in l.values())]
    for col, val in (filtres or {}).items():
        if val not in (None, "", "(tous)"):
            lignes = [l for l in lignes if sans_accents(str(val)) in sans_accents(str(l.get(col, "")))]
    cols: list[str] = ["id", "type"]
    for l in lignes:
        for k in l:
            if k not in cols:
                cols.append(k)
    if tri and tri in cols:
        def cle(l):
            v = l.get(tri)
            if v is None:
                return (1, 0, "")
            if isinstance(v, (int, float)):
                return (0, v, "")
            return (0, 0, sans_accents(str(v)))
        lignes.sort(key=cle, reverse=decroissant)
    else:
        lignes.sort(key=lambda l: l["id"])
    total = len(lignes)
    taille = max(1, taille)
    pages = max(1, -(-total // taille))
    page = min(max(1, page), pages)
    return {"total": total, "page": page, "pages": pages, "colonnes": cols,
            "lignes": lignes[(page - 1) * taille: page * taille]}


def classe_de(identifiant: str, store: BaseStore | None = None) -> str:
    """Classe la plus précise d'un individu ; NotFoundError s'il n'existe pas."""
    store = store or get_store()
    rows = store.query(f"SELECT ?t WHERE {{ sg:{identifiant} a ?t }}").rows
    schema = get_schema()
    types = [r["t"] for r in rows if r["t"] in schema.classes]
    if not types:
        raise NotFoundError(f"L'élément « {identifiant} » n'existe pas.")
    return _plus_specifique(types)


def existe(identifiant: str, store: BaseStore | None = None) -> bool:
    store = store or get_store()
    if not ID_VALIDE.match(identifiant or ""):
        return False
    return bool(store.query(f"ASK {{ sg:{identifiant} a ?t }}").boolean)


def references_entrantes(identifiant: str, store: BaseStore | None = None) -> list[dict]:
    """Éléments qui pointent vers `identifiant` (liens à rompre en cas de suppression)."""
    store = store or get_store()
    q = f"SELECT ?de ?propriete WHERE {{ ?de ?propriete sg:{identifiant} . FILTER(isIRI(?de)) }}"
    refs = [{"de": r["de"], "propriete": r["propriete"]} for r in store.query(q).rows]
    return [r for r in refs if not r["propriete"].endswith(("#first", "#rest", "#distinctMembers"))]


def fiche(identifiant: str, store: BaseStore | None = None) -> dict:
    """Fiche détail : valeurs, relations sortantes (avec noms) et relations entrantes."""
    store = store or get_store()
    cls = classe_de(identifiant, store)
    rows = store.query(f"""SELECT ?propriete ?valeur WHERE {{
  sg:{identifiant} ?propriete ?valeur .
  FILTER(!(?propriete = rdf:type && ?valeur = owl:NamedIndividual)) }}""").rows
    schema = get_schema()
    donnees: dict[str, Any] = {}
    relations: dict[str, list] = {}
    for r in rows:
        p = _cle_prop(r["propriete"])
        if p == "type" or p not in schema.props:
            continue
        if schema.props[p].type == "object":
            relations.setdefault(p, []).append(r["valeur"])
        else:
            donnees[p] = r["valeur"]
    noms = {i["id"]: i["nom"] for i in lister_ids("Thing", store)} if "Thing" in schema.classes else {}
    if not noms:
        noms = {r["id"]: r["nom"] for r in store.query(
            "SELECT ?id ?nom WHERE { ?id sg:hasName ?nom }").rows}
    return {
        "id": identifiant, "type": cls, "nom": donnees.get("hasName", identifiant),
        "donnees": donnees,
        "relations": {p: [{"id": v, "nom": noms.get(v, v)} for v in sorted(vs)] for p, vs in relations.items()},
        "references": [{**r, "nom": noms.get(r["de"], r["de"])} for r in references_entrantes(identifiant, store)],
    }


# --------------------------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------------------------
def _decimal(v: Any, label: str) -> Decimal:
    try:
        d = Decimal(str(v).replace(",", ".").strip())
        if not d.is_finite():
            raise InvalidOperation
        return d
    except (InvalidOperation, ValueError):
        raise ValidationError(f"« {label} » doit être un nombre (exemple : 12.5).") from None


def _date_heure(v: Any, label: str) -> str:
    if isinstance(v, dt.datetime):
        return v.replace(microsecond=0).isoformat()
    if isinstance(v, dt.date):
        return dt.datetime(v.year, v.month, v.day).isoformat()
    texte = str(v).strip().replace(" ", "T")
    try:
        d = dt.datetime.fromisoformat(texte)
    except ValueError:
        raise ValidationError(f"« {label} » doit être une date valide (exemple : 2024-05-17 ou 2024-05-17T08:30:00).") from None
    return d.replace(microsecond=0, tzinfo=None).isoformat()


def valider(
    cls: str, donnees: dict[str, Any], creation: bool = True, existant: dict | None = None,
    store: BaseStore | None = None, identifiant: str | None = None,
) -> dict[str, Any]:
    """Contrôle et convertit les valeurs saisies. Retourne {propriété: valeur(s) typée(s)}.

    Règles : types XSD, valeurs positives, efficacité entre 0 et 1, existence et type des cibles
    des relations, production ≤ capacité, e-mail valide et unique, champs obligatoires.
    """
    store = store or get_store()
    schema = get_schema()
    autorisees = {p.nom: p for p in schema.props_de(cls)}
    erreurs: list[str] = []
    propre: dict[str, Any] = {}
    cache_ids: dict[str, set[str]] = {}

    for nom, brut in donnees.items():
        if nom not in autorisees:
            erreurs.append(f"Le champ « {libelle_prop(nom)} » ne s'applique pas à un(e) {nom_classe(cls)}.")
            continue
        p: Prop = autorisees[nom]
        vide = brut is None or brut == "" or brut == []
        if vide:
            propre[nom] = None
            continue
        label = libelle_prop(nom)
        try:
            if p.type == "object":
                valeurs = brut if isinstance(brut, (list, tuple, set)) else [brut]
                valeurs = [str(v).strip() for v in valeurs if str(v).strip()]
                if nom in MONO_VALUEES and len(valeurs) > 1:
                    raise ValidationError(f"« {label} » n'accepte qu'une seule valeur.")
                for v in valeurs:
                    cle = "|".join(p.portee)
                    if cle not in cache_ids:
                        cache_ids[cle] = {i["id"] for portee in p.portee for i in lister_ids(portee, store)}
                    if v not in cache_ids[cle]:
                        attendu = " ou ".join(nom_classe(x) for x in p.portee)
                        raise ValidationError(f"« {label} » : « {v} » n'existe pas ou n'est pas un(e) {attendu}.")
                propre[nom] = valeurs
            else:
                type_xsd = (p.portee[0] if p.portee else "xsd:string").replace("xsd:", "")
                if type_xsd == "decimal":
                    d = _decimal(brut, label)
                    mini, strict, maxi = REGLES_NUM.get(nom, (None, False, None))
                    if mini is not None and (d < mini or (strict and d == mini)):
                        raise ValidationError(
                            f"« {label} » doit être {'strictement ' if strict else ''}positif(ve)"
                            + (" (ou nul)." if not strict else "."))
                    if maxi is not None and d > maxi:
                        raise ValidationError(f"« {label} » doit être compris entre {mini} et {maxi}.")
                    propre[nom] = d
                elif type_xsd == "dateTime":
                    propre[nom] = _date_heure(brut, label)
                else:
                    texte = str(brut).strip()
                    if nom == "hasRole" and texte not in ROLES:
                        raise ValidationError(f"« {label} » doit être l'une des valeurs : {', '.join(ROLES)}.")
                    if nom == "hasEmail":
                        if not EMAIL_RE.match(texte):
                            raise ValidationError("L'adresse e-mail n'est pas valide (exemple : nom@societe.tn).")
                        autre = store.query(
                            f'SELECT ?u WHERE {{ ?u sg:hasEmail ?m . FILTER(LCASE(STR(?m)) = "{esc_literal(texte.lower())}") }}').rows
                        if any(r["u"] != identifiant for r in autre):
                            raise ValidationError("Cette adresse e-mail est déjà utilisée par un autre utilisateur.")
                    propre[nom] = texte
        except ValidationError as exc:
            erreurs.extend(exc.erreurs)

    # Champs obligatoires
    fusion = {**{k: v for k, v in (existant or {}).items()}, **{k: v for k, v in propre.items()}}
    for req in OBLIGATOIRES:
        if req in autorisees and (fusion.get(req) in (None, "", [])):
            erreurs.append(f"Le champ « {libelle_prop(req)} » est obligatoire.")
    # Cohérence production / capacité
    cap, prod = fusion.get("hasCapacity"), fusion.get("hasPowerOutput")
    try:
        if cap is not None and prod is not None and Decimal(str(prod)) > Decimal(str(cap)):
            erreurs.append("La puissance produite ne peut pas dépasser la capacité installée.")
    except InvalidOperation:
        pass
    if erreurs:
        raise ValidationError(erreurs)
    return propre


# --------------------------------------------------------------------------------------------
# Construction SPARQL
# --------------------------------------------------------------------------------------------
def litteral(nom_prop: str, valeur: Any) -> str:
    """Littéral SPARQL typé selon la portée XSD de la propriété."""
    schema = get_schema()
    portee = (schema.props[nom_prop].portee or ["xsd:string"])[0]
    if portee == "xsd:decimal":
        return f'"{format(Decimal(str(valeur)), "f")}"^^xsd:decimal'
    if portee == "xsd:dateTime":
        return f'"{valeur}"^^xsd:dateTime'
    return f'"{esc_literal(valeur)}"^^xsd:string'


def _triplets(identifiant: str, propre: dict[str, Any]) -> list[str]:
    """Liste de triplets 'sg:id sg:p valeur .' (avec la réciproque pour les propriétés symétriques)."""
    schema = get_schema()
    res = []
    for nom, val in propre.items():
        if val is None:
            continue
        if schema.props[nom].type == "object":
            for v in val:
                res.append(f"sg:{identifiant} sg:{nom} sg:{v} .")
                if schema.props[nom].symetrique:
                    res.append(f"sg:{v} sg:{nom} sg:{identifiant} .")
        else:
            res.append(f"sg:{identifiant} sg:{nom} {litteral(nom, val)} .")
    return res


def _identifiant_libre(base: str, store: BaseStore) -> str:
    candidat, n = base, 2
    while existe(candidat, store):
        candidat = f"{base}_{n}"
        n += 1
    return candidat


# --------------------------------------------------------------------------------------------
# Écriture
# --------------------------------------------------------------------------------------------
def preparer_creation(cls: str, donnees: dict[str, Any], identifiant: str | None = None,
                      store: BaseStore | None = None) -> tuple[str, dict[str, Any], str]:
    """Valide les données et construit le INSERT DATA, sans rien écrire.
    Retourne (identifiant, valeurs validées, requête SPARQL)."""
    store = store or get_store()
    cls = resoudre_classe(cls)
    schema = get_schema()
    if schema.classes[cls]["definie"]:
        raise ValidationError(f"« {nom_classe(cls)} » est une catégorie calculée par le raisonneur : on ne peut pas y créer d'élément directement.")
    if identifiant:
        identifiant = identifiant.strip()
        if not ID_VALIDE.match(identifiant):
            raise ValidationError("L'identifiant doit commencer par une lettre et ne contenir que lettres, chiffres et « _ ».")
        if existe(identifiant, store):
            raise ValidationError(f"L'identifiant « {identifiant} » existe déjà : choisissez-en un autre.")
    else:
        nom = str(donnees.get("hasName") or "").strip()
        if not nom:
            raise ValidationError("Le champ « Nom » est obligatoire.")
        identifiant = _identifiant_libre(slug(nom), store)
    propre = valider(cls, donnees, True, None, store, identifiant)
    triplets = _triplets(identifiant, propre)
    corps = "\n  ".join([f"sg:{identifiant} a owl:NamedIndividual, sg:{cls} ."] + triplets)
    requete = f"INSERT DATA {{\n  {corps}\n}}"
    return identifiant, propre, requete


def creer(cls: str, donnees: dict[str, Any], identifiant: str | None = None, store: BaseStore | None = None) -> Op:
    """Crée un individu (SPARQL INSERT DATA) après validation complète."""
    store = store or get_store()
    cls = resoudre_classe(cls)
    identifiant, propre, requete = preparer_creation(cls, donnees, identifiant, store)
    store.update(requete)
    return Op(True, f"« {propre.get('hasName', identifiant)} » a été ajouté ({nom_classe(cls)}).", requete, {"id": identifiant})


def preparer_modification(identifiant: str, donnees: dict[str, Any],
                          store: BaseStore | None = None) -> tuple[list[str], dict[str, Any], str]:
    """Valide les changements et construit les opérations DELETE/INSERT WHERE, sans rien écrire.
    Retourne (opérations, valeurs validées, nom affichable)."""
    store = store or get_store()
    cls = classe_de(identifiant, store)
    actuel = fiche(identifiant, store)
    existant = {**actuel["donnees"], **{p: [x["id"] for x in v] for p, v in actuel["relations"].items()}}
    propre = valider(cls, donnees, False, existant, store, identifiant)
    schema = get_schema()
    operations = []
    for nom, val in propre.items():
        prop = schema.props[nom]
        if prop.type == "object" and prop.symetrique:
            operations.append(f"DELETE WHERE {{ sg:{identifiant} sg:{nom} ?x }}")
            operations.append(f"DELETE WHERE {{ ?x sg:{nom} sg:{identifiant} }}")
            if val:
                operations.append("INSERT DATA {\n  " + "\n  ".join(_triplets(identifiant, {nom: val})) + "\n}")
            continue
        nouveaux = "\n    ".join(_triplets(identifiant, {nom: val})) if val is not None else ""
        operations.append(
            f"DELETE {{ sg:{identifiant} sg:{nom} ?ancien }}\n"
            f"INSERT {{ {nouveaux} }}\n"
            f"WHERE {{ OPTIONAL {{ sg:{identifiant} sg:{nom} ?ancien }} }}"
        )
    return operations, propre, actuel["nom"]


def modifier(identifiant: str, donnees: dict[str, Any], store: BaseStore | None = None) -> Op:
    """Met à jour les propriétés fournies (SPARQL DELETE/INSERT WHERE)."""
    store = store or get_store()
    operations, propre, nom = preparer_modification(identifiant, donnees, store)
    if not operations:
        return Op(True, "Aucune modification à enregistrer.", "", {"id": identifiant})
    requete = store.update_many(operations)
    return Op(True, f"« {nom} » a été mis à jour.", requete, {"id": identifiant})


def requete_recoller_liste(identifiant: str) -> str:
    """Retire l'individu des listes RDF (owl:AllDifferent) sans casser la liste."""
    return (
        f"DELETE {{ ?avant ?lien ?c . ?c rdf:first sg:{identifiant} ; rdf:rest ?suite }}\n"
        f"INSERT {{ ?avant ?lien ?suite }}\n"
        f"WHERE {{ ?c rdf:first sg:{identifiant} ; rdf:rest ?suite . ?avant ?lien ?c .\n"
        "         FILTER(?lien IN (rdf:rest, owl:distinctMembers)) }"
    )


def operations_suppression(identifiant: str) -> list[str]:
    return [
        requete_recoller_liste(identifiant),
        f"DELETE WHERE {{ ?de ?lien sg:{identifiant} }}",
        f"DELETE WHERE {{ sg:{identifiant} ?propriete ?valeur }}",
    ]


def supprimer(identifiant: str, cascade: bool = False, store: BaseStore | None = None) -> Op:
    """Supprime un individu. Si d'autres éléments le référencent, exige `cascade=True`."""
    store = store or get_store()
    cls = classe_de(identifiant, store)
    nom = fiche(identifiant, store)["nom"]
    refs = references_entrantes(identifiant, store)
    if refs and not cascade:
        liste = ", ".join(sorted({f"{r['de']} ({libelle_prop(r['propriete'])})" for r in refs}))
        raise IntegrityError(
            f"« {nom} » est utilisé par d'autres éléments : {liste}. "
            "Confirmez la suppression en cascade pour rompre ces liens.", refs)
    requete = store.update_many(operations_suppression(identifiant))
    suite = f" et {len(refs)} lien(s) associé(s) ont été retirés" if refs else ""
    return Op(True, f"« {nom} » ({nom_classe(cls)}) a été supprimé{suite}.", requete, {"id": identifiant, "liens_retires": len(refs)})
