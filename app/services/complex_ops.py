"""CRUD complexe : opérations touchant plusieurs individus, exécutées de façon transactionnelle.

Chaque opération est annulée entièrement (rollback) si une étape échoue.
"""
from __future__ import annotations

from typing import Any

from app.errors import NotFoundError, ValidationError
from app.labels import nom_classe
from app.services import crud
from app.services.common import Op
from app.sparql.store import BaseStore, get_store


def _exiger(identifiant: str, classe: str, store: BaseStore, role: str) -> None:
    """Vérifie que l'individu existe et appartient bien à la classe attendue."""
    if not crud.existe(identifiant, store):
        raise NotFoundError(f"{role} : « {identifiant} » n'existe pas.")
    schema = crud.get_schema()
    if not schema.est_sous_classe(crud.classe_de(identifiant, store), classe):
        raise ValidationError(f"{role} : « {identifiant} » n'est pas un(e) {nom_classe(classe)}.")


def _energie_de(source_id: str, store: BaseStore) -> str | None:
    rows = store.query(f"SELECT ?e WHERE {{ sg:{source_id} sg:produces ?e }} LIMIT 1").rows
    return rows[0]["e"] if rows else None


def creer_batiment_lie(
    classe: str, donnees: dict[str, Any], source: str | None, noeud: str | None,
    batterie: str | None = None, store: BaseStore | None = None,
) -> Op:
    """Crée un bâtiment ET le relie à une source et à un nœud en une seule transaction.

    Si une étape échoue (source inconnue, valeur invalide…), rien n'est enregistré.
    """
    store = store or get_store()
    classe = crud.resoudre_classe(classe)
    if not crud.get_schema().est_sous_classe(classe, "Building"):
        raise ValidationError("Seuls les bâtiments peuvent être créés avec cette opération.")
    with store.transaction():
        if source:
            _exiger(source, "EnergySource", store, "Source d'énergie")
        if noeud:
            _exiger(noeud, "GridNode", store, "Nœud du réseau")
        if batterie:
            _exiger(batterie, "EnergyStorage", store, "Batterie")
        liens: dict[str, Any] = dict(donnees)
        if source:
            liens["suppliedBy"] = source
            energie = _energie_de(source, store)
            if energie and not liens.get("consumes"):
                liens["consumes"] = energie
        if noeud:
            liens["locatedIn"] = noeud
        if batterie:
            liens["hasStorage"] = batterie
        op = crud.creer(classe, liens, store=store)
    identifiant = op.data["id"]
    morceaux = [x for x in (source, noeud, batterie) if x]
    return Op(True, f"Le bâtiment « {op.data['id']} » a été créé et relié à : {', '.join(morceaux) or 'aucun élément'}.",
              op.sparql, {"id": identifiant})


def reaffecter_batiment(batiment: str, nouvelle_source: str, store: BaseStore | None = None) -> Op:
    """Change la source qui alimente un bâtiment (l'ancienne alimentation est remplacée)."""
    store = store or get_store()
    with store.transaction():
        _exiger(batiment, "Building", store, "Bâtiment")
        _exiger(nouvelle_source, "EnergySource", store, "Nouvelle source")
        energie = _energie_de(nouvelle_source, store)
        ops = [
            f"DELETE {{ sg:{batiment} sg:suppliedBy ?ancienne }}\n"
            f"INSERT {{ sg:{batiment} sg:suppliedBy sg:{nouvelle_source} }}\n"
            f"WHERE {{ OPTIONAL {{ sg:{batiment} sg:suppliedBy ?ancienne }} }}"
        ]
        if energie:
            ops.append(
                f"DELETE {{ sg:{batiment} sg:consumes ?e }}\n"
                f"INSERT {{ sg:{batiment} sg:consumes sg:{energie} }}\n"
                f"WHERE {{ OPTIONAL {{ sg:{batiment} sg:consumes ?e }} }}")
        requete = store.update_many(ops)
    return Op(True, f"Le bâtiment « {batiment} » est maintenant alimenté par « {nouvelle_source} ».", requete)


def supprimer_source_detachee(source: str, store: BaseStore | None = None) -> Op:
    """Supprime une source d'énergie après avoir détaché tous les bâtiments et nœuds liés."""
    store = store or get_store()
    with store.transaction():
        _exiger(source, "EnergySource", store, "Source d'énergie")
        batiments = [r["b"] for r in store.query(f"SELECT ?b WHERE {{ ?b sg:suppliedBy sg:{source} }}").rows]
        requete = store.update_many([
            f"DELETE WHERE {{ ?b sg:suppliedBy sg:{source} }}",
            f"DELETE WHERE {{ ?n sg:hasSource sg:{source} }}",
            *crud.operations_suppression(source),
        ])
    msg = f"La source « {source} » a été supprimée"
    msg += f" ; {len(batiments)} bâtiment(s) sont désormais sans alimentation : {', '.join(batiments)}." if batiments else "."
    return Op(True, msg, requete, {"batiments_detaches": batiments})


def affecter_utilisateur(utilisateur: str, batiments: list[str], remplacer: bool = False,
                         store: BaseStore | None = None) -> Op:
    """Affecte un utilisateur à plusieurs bâtiments (ajout, ou remplacement des affectations)."""
    store = store or get_store()
    if not batiments:
        raise ValidationError("Choisissez au moins un bâtiment.")
    with store.transaction():
        _exiger(utilisateur, "User", store, "Utilisateur")
        for b in batiments:
            _exiger(b, "Building", store, "Bâtiment")
        ops = []
        if remplacer:
            ops.append(f"DELETE WHERE {{ sg:{utilisateur} sg:owns ?b }}")
        ops.append("INSERT DATA {\n  " + "\n  ".join(f"sg:{utilisateur} sg:owns sg:{b} ." for b in batiments) + "\n}")
        requete = store.update_many(ops)
    return Op(True, f"« {utilisateur} » possède maintenant {len(batiments)} bâtiment(s) de plus : {', '.join(batiments)}."
              if not remplacer else f"« {utilisateur} » possède désormais uniquement : {', '.join(batiments)}.", requete)
