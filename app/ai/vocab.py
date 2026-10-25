"""Vocabulaire du moteur de règles : synonymes issus de l'ontologie, détection de classes,
de propriétés et d'individus dans une phrase en français ou en anglais."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

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


# Classe -> expressions (sans accents) qui la désignent. Les expressions longues passent en premier.
SYNONYMES_CLASSES: dict[str, list[str]] = {
    "IndustrialBuilding": ["batiments? industriel(?:le)?s?", "industriel(?:le)?s?", "usines?", "factor(?:y|ies)", "industrial(?: buildings?)?"],
    "CommercialBuilding": ["batiments? commerciaux", "batiments? commercial", "commerciaux", "commercial(?:e|es)?", "centres? commerciaux?", "commerces?", "malls?"],
    "ResidentialBuilding": ["batiments? residentiel(?:le)?s?", "residentiel(?:le)?s?", "maisons?", "logements?", "habitations?", "houses?", "residential(?: buildings?)?"],
    "Building": ["batiments?", "immeubles?", "buildings?", "constructions?"],
    "SolarSource": ["sources? solaires?", "fermes? solaires?", "centrales? solaires?", "panneaux? solaires?", "photovoltaiques?", "solar(?: sources?| farms?)?", "solaires?"],
    "WindSource": ["sources? eoliennes?", "parcs? eoliens?", "fermes? eoliennes?", "eoliennes?", "eoliens?", "wind(?: sources?| farms?| turbines?)?"],
    "EnergySource": ["sources? d energie", "sources? energetiques?", "sources?", "producteurs?", "energy sources?"],
    "BatteryStorage": ["batteries", "batterie", "batteries? de stockage", "batter(?:y|ies)"],
    "EnergyStorage": ["stockages?", "systemes? de stockage", "storage(?:s)?"],
    "GridNode": ["noe?uds? du reseau", "noe?uds?", "grid nodes?", "nodes?"],
    "Substation": ["postes? electriques?", "postes?", "sous stations?", "substations?"],
    "GridElement": ["elements? du reseau", "grid elements?"],
    "User": ["utilisateurs?", "proprietaires?", "gestionnaires?", "users?", "owners?"],
    "NonRenewableEnergy": ["energies? non renouvelables?", "non renewable energ(?:y|ies)"],
    "RenewableEnergy": ["energies? renouvelables?", "renewable energ(?:y|ies)"],
    "Energy": ["energies?", "energy"],
}

# Propriété -> expressions
SYNONYMES_PROPS: dict[str, list[str]] = {
    "hasStorageCapacity": ["capacites? de stockage", "capacites? stockees?", "storage capacity"],
    "hasPowerOutput": ["puissances? produites?", "production", "puissance", "power output", "output", "produit(?:e|es)?"],
    "hasCapacity": ["capacites? installees?", "capacites?", "capacity"],
    "hasConsumption": ["consommations?", "consommation", "consumption", "consomme(?:nt)?"],
    "hasEfficiency": ["efficacites?", "rendements?", "efficiency"],
    "hasVoltage": ["tensions?", "voltage", "kv"],
    "hasLocation": ["localisations?", "lieux?", "emplacements?", "location", "ville"],
    "hasEmail": ["e ?mails?", "courriels?", "mails?"],
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
    "noeud noeuds nouds noud poste postes centre centres commercial commerciaux batiment batiments source sources de du des la le "
    "les l d un une et energie utilisateur utilisateurs en sur au aux a".split()
)

STOP_MOTS = set("le la les l un une des du de d et ou a au aux en dans sur par pour est sont qui que quels quelles quel quelle".split())


@dataclass
class Individu:
    id: str
    nom: str
    classe: str


def compiler(synonymes: dict[str, list[str]]) -> list[tuple[str, re.Pattern]]:
    """Compile les expressions, les plus longues d'abord."""
    paires = [(cle, expr) for cle, exprs in synonymes.items() for expr in exprs]
    paires.sort(key=lambda p: -len(p[1]))
    return [(cle, re.compile(rf"(?<![a-z0-9]){expr}(?![a-z0-9])")) for cle, expr in paires]


CLASSES_RE = compiler(SYNONYMES_CLASSES)
PROPS_RE = compiler(SYNONYMES_PROPS)


def trouver(phrase_norm: str, regles: list[tuple[str, re.Pattern]]) -> list[tuple[str, int, int]]:
    """Retourne (clé, début, fin) pour chaque motif trouvé sans chevauchement (les longs gagnent)."""
    pris: list[tuple[str, int, int]] = []
    for cle, motif in regles:
        for m in motif.finditer(phrase_norm):
            if m.end() == m.start():
                continue
            if any(not (m.end() <= d or m.start() >= f) for _, d, f in pris):
                continue
            pris.append((cle, m.start(), m.end()))
    return sorted(pris, key=lambda x: x[1])


def classes_dans(phrase_norm: str) -> list[tuple[str, int, int]]:
    return trouver(phrase_norm, CLASSES_RE)


def props_dans(phrase_norm: str) -> list[tuple[str, int, int]]:
    return trouver(phrase_norm, PROPS_RE)


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
    jetons_phrase = set(_jetons(p_norm))
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
