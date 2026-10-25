"""Accès au graphe RDF : rdflib en mémoire (persisté dans le .owl) ou Apache Jena Fuseki.

Les deux implémentations exposent la même interface (`query`, `update`, `transaction`,
`snapshot`, `restore`, `serialize`) : le reste de l'application ignore le moteur utilisé.
"""
from __future__ import annotations

import datetime as dt
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterator

import httpx
from rdflib import BNode, Graph, Literal, URIRef
from rdflib.query import Result

from app.config import settings
from app.errors import SmartGridError
from app.sparql.prefixes import local_name, with_prefixes


@dataclass
class QueryResult:
    """Résultat normalisé d'une requête SPARQL (SELECT, ASK ou CONSTRUCT)."""

    kind: str  # "select" | "ask" | "construct"
    vars: list[str] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)
    boolean: bool | None = None

    def __len__(self) -> int:
        return len(self.rows)

    def to_dict(self) -> dict:
        return {"kind": self.kind, "vars": self.vars, "rows": self.rows, "boolean": self.boolean}


def _valeur(terme: Any, raccourcir: bool = True) -> Any:
    """Convertit un terme RDF en valeur Python simple (noms locaux pour l'ontologie)."""
    if terme is None:
        return None
    if isinstance(terme, URIRef):
        return local_name(str(terme)) if raccourcir else str(terme)
    if isinstance(terme, BNode):
        return f"_:{terme}"
    if isinstance(terme, Literal):
        v = terme.toPython()
        if isinstance(v, Decimal):
            return float(v)
        if isinstance(v, (dt.datetime, dt.date)):
            return v.isoformat()
        if isinstance(v, (int, float, bool, str)):
            return v
        return str(terme)
    return str(terme)


def _normaliser(res: Result, raccourcir: bool) -> QueryResult:
    if res.type == "ASK":
        return QueryResult("ask", boolean=bool(res.askAnswer))
    if res.type == "CONSTRUCT":
        lignes = [
            {"s": _valeur(s, raccourcir), "p": _valeur(p, raccourcir), "o": _valeur(o, raccourcir)}
            for s, p, o in res.graph
        ]
        return QueryResult("construct", ["s", "p", "o"], lignes)
    noms = [str(v) for v in res.vars]
    lignes = [{n: _valeur(row[n], raccourcir) for n in noms} for row in res]
    return QueryResult("select", noms, lignes)


class BaseStore:
    """Interface commune aux deux moteurs."""

    persist: bool = True

    def __init__(self) -> None:
        self._verrou = threading.RLock()
        self._profondeur = 0

    # -- à implémenter ----------------------------------------------------------------------
    def query(self, requete: str, raccourcir: bool = True) -> QueryResult:  # pragma: no cover
        raise NotImplementedError

    def _update(self, requete: str) -> None:  # pragma: no cover
        raise NotImplementedError

    def snapshot(self) -> Graph:  # pragma: no cover
        raise NotImplementedError

    def restore(self, graphe: Graph) -> None:  # pragma: no cover
        raise NotImplementedError

    def save(self) -> None:  # pragma: no cover
        raise NotImplementedError

    # -- écriture ---------------------------------------------------------------------------
    def update(self, requete: str) -> None:
        """Exécute un SPARQL Update ; sauvegarde immédiate hors transaction."""
        with self._verrou:
            if self._profondeur == 0:
                avant = self.snapshot()
                try:
                    self._update(with_prefixes(requete))
                except BaseException:
                    self.restore(avant)
                    raise
                self.save()
            else:
                self._update(with_prefixes(requete))

    def update_many(self, operations: list[str]) -> str:
        """Exécute plusieurs opérations en une seule requête ; retourne le texte affichable."""
        texte = " ;\n".join(operations)
        self.update(texte)
        return texte

    @contextmanager
    def transaction(self) -> Iterator["BaseStore"]:
        """Transaction logique : tout est annulé (rollback) si une erreur survient."""
        with self._verrou:
            instantane = self.snapshot() if self._profondeur == 0 else None
            self._profondeur += 1
            try:
                yield self
            except BaseException:
                self._profondeur -= 1
                if instantane is not None:
                    self.restore(instantane)
                raise
            else:
                self._profondeur -= 1
                if self._profondeur == 0:
                    self.save()

    # -- utilitaires ------------------------------------------------------------------------
    def serialize(self, fmt: str = "xml") -> str:
        return self.snapshot().serialize(format=fmt)


class RdflibStore(BaseStore):
    """Graphe en mémoire, rechargé automatiquement si le fichier .owl change sur le disque."""

    def __init__(self, chemin: Path | str | None = None, persist: bool = True, graphe: Graph | None = None):
        super().__init__()
        self.chemin = Path(chemin) if chemin else settings.owl_path
        self.persist = persist
        self.graph = graphe if graphe is not None else Graph()
        self._mtime = 0.0
        if graphe is None:
            self._charger()

    @classmethod
    def depuis_graphe(cls, graphe: Graph) -> "RdflibStore":
        """Magasin purement mémoire (jamais écrit sur disque) : simulations, tests."""
        return cls(chemin=Path("memoire.owl"), persist=False, graphe=graphe)

    def _charger(self) -> None:
        if not self.chemin.exists():
            raise SmartGridError(f"Le fichier d'ontologie est introuvable : {self.chemin}")
        g = Graph()
        g.parse(self.chemin, format="xml")
        self.graph = g
        self._mtime = self.chemin.stat().st_mtime

    def _rafraichir(self) -> None:
        if self.persist and self._profondeur == 0 and self.chemin.exists() \
                and self.chemin.stat().st_mtime > self._mtime + 1e-6:
            self._charger()

    def query(self, requete: str, raccourcir: bool = True) -> QueryResult:
        with self._verrou:
            self._rafraichir()
            return _normaliser(self.graph.query(with_prefixes(requete)), raccourcir)

    def _update(self, requete: str) -> None:
        self._rafraichir()
        self.graph.update(requete)

    def snapshot(self) -> Graph:
        with self._verrou:
            self._rafraichir()
            copie = Graph()
            for prefixe, ns in self.graph.namespaces():
                copie.bind(prefixe, ns)
            for t in self.graph:
                copie.add(t)
            return copie

    def restore(self, graphe: Graph) -> None:
        with self._verrou:
            self.graph.remove((None, None, None))
            for t in graphe:
                self.graph.add(t)

    def save(self) -> None:
        if not self.persist:
            return
        sauvegarde = self.chemin.with_suffix(".owl.bak")
        if not sauvegarde.exists() and self.chemin.exists():
            sauvegarde.write_bytes(self.chemin.read_bytes())
        tmp = self.chemin.with_suffix(".owl.tmp")
        self.graph.serialize(destination=str(tmp), format="xml")
        tmp.replace(self.chemin)
        self._mtime = self.chemin.stat().st_mtime


class FusekiStore(BaseStore):
    """Client HTTP d'Apache Jena Fuseki (SPARQL 1.1 Query / Update / Graph Store)."""

    def __init__(self, base: str | None = None, dataset: str | None = None):
        super().__init__()
        self.base = f"{(base or settings.fuseki_url)}/{dataset or settings.fuseki_dataset}"
        self.client = httpx.Client(timeout=30)
        self._initialiser()

    def _initialiser(self) -> None:
        """Charge le fichier .owl dans Fuseki si le jeu de données est vide."""
        try:
            vide = not self.query("ASK { ?s ?p ?o }").boolean
        except httpx.HTTPError as exc:
            raise SmartGridError(
                "Impossible de joindre Fuseki. Vérifiez que le conteneur est démarré "
                f"(docker compose up -d) et l'adresse {self.base}."
            ) from exc
        if vide:
            self._remplacer(Graph().parse(settings.owl_path, format="xml"))

    def query(self, requete: str, raccourcir: bool = True) -> QueryResult:
        requete = with_prefixes(requete)
        rep = self.client.post(
            f"{self.base}/query", data={"query": requete},
            headers={"Accept": "application/sparql-results+json, text/turtle;q=0.8"},
        )
        if rep.status_code >= 400:
            raise SmartGridError(f"Fuseki a refusé la requête : {rep.text[:300]}")
        if "turtle" in rep.headers.get("content-type", ""):
            g = Graph().parse(data=rep.text, format="turtle")
            return QueryResult("construct", ["s", "p", "o"], [
                {"s": _valeur(s, raccourcir), "p": _valeur(p, raccourcir), "o": _valeur(o, raccourcir)}
                for s, p, o in g])
        js = rep.json()
        if "boolean" in js:
            return QueryResult("ask", boolean=js["boolean"])
        noms = js["head"]["vars"]
        lignes = []
        for b in js["results"]["bindings"]:
            ligne: dict[str, Any] = {}
            for n in noms:
                if n not in b:
                    ligne[n] = None
                    continue
                t = b[n]
                if t["type"] == "uri":
                    ligne[n] = local_name(t["value"]) if raccourcir else t["value"]
                elif t["type"] == "bnode":
                    ligne[n] = "_:" + t["value"]
                else:
                    dtype = t.get("datatype", "")
                    v: Any = t["value"]
                    try:
                        if dtype.endswith(("#decimal", "#double", "#float")):
                            v = float(v)
                        elif dtype.endswith(("#integer", "#int", "#long")):
                            v = int(v)
                    except ValueError:
                        pass
                    ligne[n] = v
            lignes.append(ligne)
        return QueryResult("select", noms, lignes)

    def _update(self, requete: str) -> None:
        rep = self.client.post(f"{self.base}/update", data={"update": requete})
        if rep.status_code >= 400:
            raise SmartGridError(f"Fuseki a refusé la mise à jour : {rep.text[:300]}")

    def snapshot(self) -> Graph:
        rep = self.client.post(
            f"{self.base}/query", data={"query": "CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }"},
            headers={"Accept": "text/turtle"},
        )
        return Graph().parse(data=rep.text, format="turtle")

    def _remplacer(self, graphe: Graph) -> None:
        self._update("DELETE WHERE { ?s ?p ?o }")
        corps = graphe.serialize(format="turtle")
        rep = self.client.post(f"{self.base}/data", content=corps.encode("utf-8"),
                               headers={"Content-Type": "text/turtle; charset=utf-8"})
        if rep.status_code >= 400:
            raise SmartGridError(f"Fuseki a refusé le chargement : {rep.text[:300]}")

    def restore(self, graphe: Graph) -> None:
        self._remplacer(graphe)

    def save(self) -> None:
        """Fuseki (TDB2) persiste déjà chaque écriture ; on exporte aussi le .owl pour Protégé."""
        try:
            self.snapshot().serialize(destination=str(settings.owl_path), format="xml")
        except OSError:
            pass


_store: BaseStore | None = None
_verrou_global = threading.Lock()


def get_store() -> BaseStore:
    """Retourne le magasin unique de l'application (créé selon `SG_BACKEND`)."""
    global _store
    with _verrou_global:
        if _store is None:
            _store = FusekiStore() if settings.backend == "fuseki" else RdflibStore()
        return _store


def set_store(store: BaseStore | None) -> None:
    """Remplace le magasin global (utilisé par les tests)."""
    global _store
    _store = store
