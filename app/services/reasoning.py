"""Raisonnement OWL avec owlready2 + HermiT (Java requis), avec repli SPARQL si indisponible."""
from __future__ import annotations

import contextlib
import io
import os
import tempfile
import time
from pathlib import Path

from app.sparql.store import BaseStore, get_store


def _raisonner_hermit(store: BaseStore) -> dict:
    from owlready2 import ThingClass, World, sync_reasoner_hermit

    dossier = tempfile.mkdtemp(prefix="sg_reason_")
    fichier = Path(dossier) / "ontologie.owl"
    store.snapshot().serialize(destination=str(fichier), format="xml")
    monde = World()
    onto = monde.get_ontology("file://" + str(fichier).replace("\\", "/")).load()

    def etat_classes() -> dict[str, set[str]]:
        return {c.name: {p.name for p in c.is_a if isinstance(p, ThingClass)} for c in onto.classes()}

    def etat_individus() -> dict[str, set[str]]:
        return {i.name: {c.name for c in i.is_a if isinstance(c, ThingClass)} for i in onto.individuals()}

    def etat_liens() -> set[tuple[str, str, str]]:
        liens = set()
        for i in onto.individuals():
            for p in i.get_properties():
                if p.name.startswith("has") and not hasattr(p, "range_iri"):
                    pass
                try:
                    for v in p[i]:
                        if hasattr(v, "name") and not isinstance(v, ThingClass):
                            liens.add((i.name, p.name, v.name))
                except Exception:  # propriété de données ou annotation
                    continue
        return liens

    classes_avant, individus_avant, liens_avant = etat_classes(), etat_individus(), etat_liens()
    debut = time.time()
    journal = io.StringIO()
    with onto, contextlib.redirect_stdout(journal):
        sync_reasoner_hermit(monde, infer_property_values=True, debug=0)
    duree = time.time() - debut
    classes_apres, individus_apres, liens_apres = etat_classes(), etat_individus(), etat_liens()
    incoherentes = sorted(c.name for c in monde.inconsistent_classes())

    types_inferes = [
        {"individu": nom, "types_ajoutes": sorted(apres - individus_avant.get(nom, set()))}
        for nom, apres in individus_apres.items() if apres - individus_avant.get(nom, set())
    ]
    sous_classes = [
        {"classe": nom, "nouvelles_super_classes": sorted(apres - classes_avant.get(nom, set()))}
        for nom, apres in classes_apres.items() if apres - classes_avant.get(nom, set())
    ]
    liens = [{"sujet": s, "propriete": p, "objet": o} for s, p, o in sorted(liens_apres - liens_avant)]
    return {
        "moteur": "HermiT (owlready2)", "coherent": not incoherentes, "classes_incoherentes": incoherentes,
        "types_inferes": sorted(types_inferes, key=lambda x: x["individu"]),
        "sous_classes_inferees": sous_classes, "liens_inferes": liens, "duree_s": round(duree, 2),
        "journal": journal.getvalue()[-2000:],
    }


def _raisonner_sparql(store: BaseStore, raison: str) -> dict:
    """Repli : calcule les bâtiments « renouvelables » par SPARQL (équivalent de la classe définie)."""
    debut = time.time()
    rows = store.query("""SELECT DISTINCT ?individu WHERE {
  ?individu a/rdfs:subClassOf* sg:Building ; sg:suppliedBy ?s .
  ?s a/rdfs:subClassOf* sg:EnergySource ; sg:produces ?e .
  ?e a/rdfs:subClassOf* sg:RenewableEnergy }""").rows
    return {
        "moteur": "Repli SPARQL (HermiT indisponible : " + raison + ")", "coherent": None,
        "classes_incoherentes": [],
        "types_inferes": [{"individu": r["individu"], "types_ajoutes": ["RenewableBuilding"]} for r in rows],
        "sous_classes_inferees": [], "liens_inferes": [], "duree_s": round(time.time() - debut, 2), "journal": "",
    }


def lancer_raisonnement(store: BaseStore | None = None, forcer_repli: bool = False) -> dict:
    """Lance HermiT sur une copie de l'ontologie (la base n'est pas modifiée)."""
    store = store or get_store()
    if forcer_repli:
        return _raisonner_sparql(store, "demandé")
    try:
        return _raisonner_hermit(store)
    except Exception as exc:  # Java absent, ontologie incohérente, etc.
        message = str(exc).strip().splitlines()[-1][:200] if str(exc).strip() else exc.__class__.__name__
        if "nconsistent" in str(exc):
            return {"moteur": "HermiT (owlready2)", "coherent": False, "classes_incoherentes": [],
                    "types_inferes": [], "sous_classes_inferees": [], "liens_inferes": [], "duree_s": 0,
                    "journal": str(exc)[-500:]}
        return _raisonner_sparql(store, message)


def verifier_coherence(store: BaseStore | None = None) -> dict:
    """Vérifie la cohérence de l'ontologie (HermiT) et résume le résultat en français."""
    res = lancer_raisonnement(store)
    if res["coherent"] is True:
        res["message"] = "L'ontologie est cohérente : aucune contradiction détectée."
    elif res["coherent"] is False:
        res["message"] = ("L'ontologie est incohérente : "
                          + (", ".join(res["classes_incoherentes"]) or "contradiction globale détectée par le raisonneur."))
    else:
        res["message"] = "Cohérence non vérifiée (raisonneur indisponible)."
    return res
