"""Étape 0 : lecture du schéma de l'ontologie (classes, hiérarchie, propriétés, domaines, portées).

Le schéma est extrait du fichier OWL avec rdflib ; il alimente les formulaires dynamiques, la
validation, le moteur NL→SPARQL et le résumé fourni au LLM.

Exécution en ligne de commande :  python -m app.sparql.schema
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from rdflib import OWL, RDF, RDFS, XSD, BNode, Graph, URIRef

from app.config import NS, settings
from app.sparql.prefixes import local_name

THING = str(OWL.Thing)


@dataclass
class Prop:
    nom: str
    type: str  # "object" | "data"
    domaine: list[str] = field(default_factory=list)
    portee: list[str] = field(default_factory=list)  # classes (object) ou type XSD (data)
    symetrique: bool = False
    label: str = ""


@dataclass
class Schema:
    classes: dict[str, dict]  # nom -> {parents, enfants, definie, commentaire}
    props: dict[str, Prop]

    # -- hiérarchie -------------------------------------------------------------------------
    def ancetres(self, cls: str) -> list[str]:
        """Classe elle-même + tous ses ancêtres (ordre : du plus proche au plus lointain)."""
        vus, pile = [], [cls]
        while pile:
            c = pile.pop(0)
            if c in vus or c not in self.classes:
                continue
            vus.append(c)
            pile.extend(self.classes[c]["parents"])
        return vus

    def descendants(self, cls: str) -> list[str]:
        """Classe elle-même + tous ses descendants."""
        vus, pile = [], [cls]
        while pile:
            c = pile.pop(0)
            if c in vus or c not in self.classes:
                continue
            vus.append(c)
            pile.extend(self.classes[c]["enfants"])
        return vus

    def est_sous_classe(self, cls: str, parent: str) -> bool:
        return parent in self.ancetres(cls)

    # -- propriétés applicables -------------------------------------------------------------
    def props_de(self, cls: str, type_: str | None = None) -> list[Prop]:
        """Propriétés dont le domaine est la classe, un de ses ancêtres, ou owl:Thing."""
        anc = set(self.ancetres(cls)) | {"Thing"}
        res = []
        for p in self.props.values():
            if type_ and p.type != type_:
                continue
            if not p.domaine or anc & set(p.domaine):
                res.append(p)
        return res

    def classes_principales(self) -> list[str]:
        """Classes sans parent, hors classes définies auxiliaires (Renewable*)."""
        return [c for c, d in self.classes.items() if not d["parents"] and not d["definie"]]

    def classes_concretes(self) -> list[str]:
        """Classes (non définies) qui peuvent instancier des individus dans les formulaires."""
        return [c for c, d in self.classes.items() if not d["definie"]]


def _nom(terme) -> str | None:
    if isinstance(terme, URIRef):
        s = str(terme)
        if s == THING:
            return "Thing"
        if s.startswith(str(XSD)):
            return "xsd:" + s[len(str(XSD)):]
        return local_name(s)
    return None


def lire_schema(graphe: Graph) -> Schema:
    """Construit le `Schema` à partir d'un graphe rdflib contenant l'ontologie."""
    classes: dict[str, dict] = {}
    for c in graphe.subjects(RDF.type, OWL.Class):
        n = _nom(c)
        if n and str(c).startswith(NS):
            classes[n] = {"parents": [], "enfants": [], "definie": False, "commentaire": ""}
    for c, d in classes.items():
        uri = URIRef(NS + c)
        for parent in graphe.objects(uri, RDFS.subClassOf):
            p = _nom(parent)
            if p and p in classes:
                d["parents"].append(p)
                classes[p]["enfants"].append(c)
        d["definie"] = any(True for _ in graphe.objects(uri, OWL.equivalentClass))
        d["commentaire"] = next((str(o) for o in graphe.objects(uri, RDFS.comment)), "")
    # Les classes définies sont placées sous leur classe de base (intersection) pour la navigation
    for c, d in classes.items():
        if d["definie"]:
            uri = URIRef(NS + c)
            for eq in graphe.objects(uri, OWL.equivalentClass):
                for liste in graphe.objects(eq, OWL.intersectionOf):
                    for membre in graphe.items(liste):
                        m = _nom(membre)
                        if m in classes and m not in d["parents"] and not isinstance(membre, BNode):
                            d["parents"].append(m)
                            classes[m]["enfants"].append(c)
                            break
    props: dict[str, Prop] = {}
    for type_, cible in (("object", OWL.ObjectProperty), ("data", OWL.DatatypeProperty)):
        for p in graphe.subjects(RDF.type, cible):
            n = _nom(p)
            if not n:
                continue
            props[n] = Prop(
                nom=n,
                type=type_,
                domaine=[x for x in (_nom(o) for o in graphe.objects(p, RDFS.domain)) if x],
                portee=[x for x in (_nom(o) for o in graphe.objects(p, RDFS.range)) if x],
                symetrique=(p, RDF.type, OWL.SymmetricProperty) in graphe,
            )
    return Schema(classes, props)


@lru_cache(maxsize=1)
def _schema_fichier(chemin: str, mtime: float) -> Schema:
    g = Graph()
    g.parse(chemin, format="xml")
    return lire_schema(g)


def get_schema() -> Schema:
    """Schéma de l'ontologie (mis en cache, relu si le fichier .owl change)."""
    chemin = settings.owl_path
    return _schema_fichier(str(chemin), chemin.stat().st_mtime)


def schema_en_texte(schema: Schema | None = None) -> str:
    """Résumé textuel du schéma (classes, hiérarchie, propriétés) : utilisé comme contexte du LLM."""
    s = schema or get_schema()
    lignes = [f"Espace de noms (préfixe sg:) : {NS}", "", "CLASSES (hiérarchie) :"]

    def afficher(c: str, niveau: int, vus: set[str]) -> None:
        if c in vus:
            return
        vus.add(c)
        d = s.classes[c]
        suffixe = "  [classe définie]" if d["definie"] else ""
        lignes.append("  " * niveau + f"- sg:{c}{suffixe}")
        for e in sorted(d["enfants"]):
            afficher(e, niveau + 1, vus)

    vus: set[str] = set()
    for racine in sorted(c for c, d in s.classes.items() if not d["parents"]):
        afficher(racine, 1, vus)
    lignes += ["", "PROPRIÉTÉS D'OBJET (domaine -> portée) :"]
    for p in sorted(s.props.values(), key=lambda x: x.nom):
        if p.type == "object":
            sym = " [symétrique]" if p.symetrique else ""
            lignes.append(f"  - sg:{p.nom} : {', '.join(p.domaine) or 'Thing'} -> {', '.join(p.portee) or 'Thing'}{sym}")
    lignes += ["", "PROPRIÉTÉS DE DONNÉES (domaine -> type) :"]
    for p in sorted(s.props.values(), key=lambda x: x.nom):
        if p.type == "data":
            lignes.append(f"  - sg:{p.nom} : {', '.join(p.domaine) or 'Thing'} -> {', '.join(p.portee) or '?'}")
    lignes += [
        "",
        "REMARQUES : les individus sont typés avec leur classe la plus précise ; pour trouver toutes les "
        "instances d'une classe, utiliser  ?x a/rdfs:subClassOf* sg:Classe .",
    ]
    return "\n".join(lignes)


def schema_en_json(schema: Schema | None = None) -> dict:
    s = schema or get_schema()
    return {
        "namespace": NS,
        "classes": s.classes,
        "proprietes": {n: p.__dict__ for n, p in s.props.items()},
    }


def generer_resume(dossier: Path | None = None) -> Path:
    """Écrit data/schema_summary.md et data/schema_summary.json (Étape 0)."""
    dossier = dossier or settings.data_dir
    s = get_schema()
    md = dossier / "schema_summary.md"
    md.write_text("# Résumé du schéma SmartGrid-Semantic\n\n```\n" + schema_en_texte(s) + "\n```\n", encoding="utf-8")
    (dossier / "schema_summary.json").write_text(
        json.dumps(schema_en_json(s), ensure_ascii=False, indent=2), encoding="utf-8")
    return md


if __name__ == "__main__":
    print(schema_en_texte())
    print("\nRésumé écrit dans :", generer_resume())
