"""Vocabulaire du moteur NLP : expressions françaises/anglaises associées aux classes, propriétés et individus
de l'ontologie. Le repérage s'appuie sur spaCy (lemmes, PhraseMatcher) : voir `app/ai/nlp.py`."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache

from app.ai import nlp
from app.sparql.schema import get_schema
from app.sparql.store import BaseStore


def normaliser(texte: str) -> str:
    """Minuscule, sans accents, apostrophes remplacées par des espaces ; la longueur est conservée
    (un caractère de sortie par caractère d'entrée) pour retrouver les positions dans le texte brut."""
    sortie = []
    for c in texte:
        d = unicodedata.normalize("NFD", c)[0]
        d = {"œ": "o", "Œ": "o", "’": " ", "'": " ", "-": " "}.get(c, d)
        sortie.append(d.lower())
    return "".join(sortie)


# Classe -> expressions (au singulier : le lemmatiseur gère pluriels et accords)
SYNONYMES_CLASSES: dict[str, list[str]] = {
    "IndustrialBuilding": ["bâtiment industriel", "industriel", "usine", "factory", "industrial building", "industrial"],
    "CommercialBuilding": ["bâtiment commercial", "commercial", "centre commercial", "commerce", "mall",
                           "commercial building"],
    "ResidentialBuilding": ["bâtiment résidentiel", "résidentiel", "maison", "logement", "habitation", "house",
                            "houses", "residential building", "residential"],
    "Building": ["bâtiment", "immeuble", "building", "buildings", "construction"],
    "SolarSource": ["source solaire", "ferme solaire", "centrale solaire", "panneau solaire", "photovoltaïque",
                    "solar source", "solar sources", "solar farm", "solar farms", "solar", "solaire"],
    "WindSource": ["source éolienne", "parc éolien", "ferme éolienne", "éolienne", "éolien", "wind source",
                   "wind sources", "wind farm", "wind farms", "wind turbine", "wind"],
    "EnergySource": ["source d'énergie", "source énergétique", "source", "producteur", "energy source",
                     "energy sources", "sources"],
    "BatteryStorage": ["batterie", "batteries", "battery"],
    "EnergyStorage": ["stockage", "système de stockage", "storage"],
    "GridNode": ["nœud du réseau", "nœud", "noeud", "noeuds", "node", "nodes", "grid node"],
    "Substation": ["poste électrique", "poste", "sous-station", "substation", "substations"],
    "GridElement": ["élément du réseau", "grid element"],
    "User": ["utilisateur", "propriétaire", "gestionnaire", "user", "users", "owner", "owners"],
    "NonRenewableEnergy": ["énergie non renouvelable", "non renewable energy"],
    "RenewableEnergy": ["énergie renouvelable", "renewable energy"],
    "Energy": ["énergie", "energy"],
}

SYNONYMES_PROPS: dict[str, list[str]] = {
    "hasStorageCapacity": ["capacité de stockage", "capacité stockée", "storage capacity"],
    "hasPowerOutput": ["puissance produite", "production", "puissance", "power output", "output"],
    "hasCapacity": ["capacité installée", "capacité", "capacity"],
    "hasConsumption": ["consommation", "consumption", "consommer"],
    "hasEfficiency": ["efficacité", "rendement", "efficiency"],
    "hasVoltage": ["tension", "voltage", "kv"],
    "hasLocation": ["localisation", "lieu", "emplacement", "location", "ville"],
    "hasEmail": ["e-mail", "email", "courriel", "mail"],
}

PROP_VAR = {
    "hasCapacity": "capacite", "hasPowerOutput": "puissance_produite", "hasConsumption": "consommation",
    "hasStorageCapacity": "capacite_stockage", "hasEfficiency": "efficacite", "hasVoltage": "tension",
    "hasLocation": "localisation", "hasInstallationDate": "date_installation", "hasEmail": "email",
    "hasRole": "role",
}

# Mots courants du vocabulaire (non discriminants pour retrouver un individu par son nom)
MOTS_GENERIQUES = set(
    "ferme fermes solaire solaires parc parcs eolien eolienne eoliens batterie batteries usine usines maison maisons "
    "noeud noeuds poste postes centre centres commercial commerciaux batiment batiments source sources de du des la le "
    "les l d un une et energie utilisateur utilisateurs en sur au aux a".split()
)

STOP_MOTS = set("le la les l un une des du de d et ou a au aux en dans sur par pour est sont qui que quels quelles quel quelle".split())


@dataclass
class Individu:
    id: str
    nom: str
    classe: str


@lru_cache(maxsize=1)
def _repereur_classes() -> nlp.Repereur:
    return nlp.Repereur(SYNONYMES_CLASSES)


@lru_cache(maxsize=1)
def _repereur_props() -> nlp.Repereur:
    return nlp.Repereur(SYNONYMES_PROPS)


def _analyse(texte: "str | nlp.Analyse") -> nlp.Analyse:
    return texte if isinstance(texte, nlp.Analyse) else nlp.analyser(texte)


def classes_dans(texte: "str | nlp.Analyse") -> list[tuple[str, int, int]]:
    """Classes citées dans la phrase : (classe, début, fin) en caractères."""
    return _repereur_classes().trouver(_analyse(texte))


def props_dans(texte: "str | nlp.Analyse") -> list[tuple[str, int, int]]:
    """Propriétés citées dans la phrase : (propriété, début, fin) en caractères."""
    return _repereur_props().trouver(_analyse(texte))


def individus_connus(store: BaseStore) -> list[Individu]:
    """Tous les individus nommés du graphe (pour retrouver « ESPRIT », « Batterie Tunis 01 »…)."""
    schema = get_schema()
    res = store.query("""SELECT ?id ?nom ?t WHERE { ?id a owl:NamedIndividual ; a ?t . OPTIONAL { ?id sg:hasName ?nom }
  FILTER(?t != owl:NamedIndividual) }""").rows
    meilleurs: dict[str, Individu] = {}
    for r in res:
        if r["t"] not in schema.classes or not isinstance(r["id"], str):
            continue
        courant = meilleurs.get(r["id"])
        if courant is None or len(schema.ancetres(r["t"])) > len(schema.ancetres(courant.classe)):
            meilleurs[r["id"]] = Individu(r["id"], r["nom"] or r["id"], r["t"])
    return list(meilleurs.values())


def _jetons(texte_norm: str) -> list[str]:
    return [j for j in re.split(r"[^a-z0-9]+", texte_norm) if j]


def trouver_individu(phrase: str, individus: list[Individu], exclure: tuple[int, int] | None = None) -> Individu | None:
    """Retrouve l'individu cité dans la phrase (nom complet, identifiant ou nom partiel distinctif)."""
    p_norm = normaliser(phrase)
    jetons_phrase = {nlp.sans_accents(t.text) for t in nlp.get_nlp().make_doc(phrase)} | set(_jetons(p_norm))
    meilleur: tuple[float, int, Individu] | None = None
    ex_egaux = 0
    for ind in individus:
        noms = {normaliser(ind.nom), normaliser(ind.id.replace("_", " "))}
        score = 0.0
        for nom in noms:
            if nom and re.search(rf"(?<![a-z0-9]){re.escape(nom)}(?![a-z0-9])", p_norm):
                score = max(score, 10 + len(nom) / 100)
        if not score:
            jetons_nom = [j for j in _jetons(normaliser(ind.nom)) if j not in STOP_MOTS]
            distinctifs = [j for j in jetons_nom if j not in MOTS_GENERIQUES]
            trouves = [j for j in distinctifs if j in jetons_phrase]
            if distinctifs and trouves and len(trouves) >= max(1, len(distinctifs) - 1) \
                    and any(j in jetons_phrase for j in jetons_nom if j in MOTS_GENERIQUES):
                score = 5 + len(trouves) / len(distinctifs)
        if score:
            if meilleur is None or score > meilleur[0]:
                meilleur, ex_egaux = (score, 0, ind), 0
            elif score == meilleur[0]:
                ex_egaux += 1
    if meilleur is None or ex_egaux:
        return None
    return meilleur[2]
