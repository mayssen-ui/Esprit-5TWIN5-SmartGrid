"""Niveau 2 du NL→SPARQL : génération de SPARQL par un LLM (API Claude), avec exemples few-shot."""
from __future__ import annotations

import re

from app.config import settings
from app.errors import SmartGridError
from app.sparql.prefixes import PREFIXES
from app.sparql.schema import schema_en_texte

EXEMPLES = [
    ("Citer les différents bâtiments",
     "SELECT ?batiment ?nom WHERE { ?batiment a/rdfs:subClassOf* sg:Building ; sg:hasName ?nom } ORDER BY ?nom"),
    ("Quels bâtiments sont alimentés par une ferme solaire ?",
     "SELECT ?nom_batiment ?nom_source WHERE { ?b a/rdfs:subClassOf* sg:Building ; sg:hasName ?nom_batiment ; sg:suppliedBy ?s . "
     "?s a/rdfs:subClassOf* sg:SolarSource ; sg:hasName ?nom_source }"),
    ("Quelle est la consommation totale des bâtiments industriels ?",
     "SELECT (SUM(?c) AS ?consommation_totale) WHERE { ?b a/rdfs:subClassOf* sg:IndustrialBuilding ; sg:hasConsumption ?c }"),
    ("Quelles sources ont un taux d'utilisation supérieur à 80 % ?",
     "SELECT ?nom ?taux WHERE { ?s a/rdfs:subClassOf* sg:EnergySource ; sg:hasName ?nom ; sg:hasCapacity ?cap ; "
     "sg:hasPowerOutput ?p . BIND(?p / ?cap AS ?taux) FILTER(?taux > 0.8) } ORDER BY DESC(?taux)"),
    ("Ajouter une batterie nommée Batterie Sfax de capacité 8",
     'INSERT DATA { sg:Batterie_Sfax a owl:NamedIndividual, sg:BatteryStorage ; sg:hasName "Batterie Sfax"^^xsd:string ; '
     'sg:hasStorageCapacity "8"^^xsd:decimal . }'),
]

SYSTEME = """Tu es un expert SPARQL 1.1. Tu traduis des questions en français ou en anglais en UNE requête SPARQL
pour l'ontologie SmartGrid décrite ci-dessous.

RÈGLES STRICTES
- Réponds UNIQUEMENT avec la requête SPARQL, sans explication, sans commentaire, sans balises ```.
- Utilise uniquement les classes et propriétés listées dans le schéma, avec le préfixe sg:.
- Pour inclure les sous-classes, utilise  ?x a/rdfs:subClassOf* sg:Classe .
- Pour les lectures, utilise SELECT, ASK ou CONSTRUCT. N'utilise jamais SERVICE, LOAD, DROP, CLEAR.
- Pour une demande d'ajout ou de suppression, utilise INSERT DATA / DELETE (les identifiants sont de la forme sg:Nom_Sans_Espace).
- Les valeurs numériques de l'ontologie sont des xsd:decimal ; ajoute toujours un nom lisible (sg:hasName) dans les SELECT.
- Les préfixes suivants sont déjà déclarés (ne les redéclare pas) :
""" + PREFIXES + """
SCHÉMA DE L'ONTOLOGIE
{schema}

EXEMPLES
{exemples}
"""


def disponible() -> bool:
    return bool(settings.anthropic_key)


def nettoyer(texte: str) -> str:
    """Retire les balises de code et les lignes PREFIX éventuelles renvoyées par le modèle."""
    texte = texte.strip()
    m = re.search(r"```(?:sparql)?\s*(.*?)```", texte, re.DOTALL | re.IGNORECASE)
    if m:
        texte = m.group(1).strip()
    return texte


def generer_sparql(question: str) -> str:
    """Demande au LLM une requête SPARQL pour la question. Lève SmartGridError si indisponible."""
    if not disponible():
        raise SmartGridError(
            "Aucun modèle prédéfini ne correspond à cette question, et l'assistant IA n'est pas configuré. "
            "Ajoutez votre clé dans la variable ANTHROPIC_API_KEY (fichier .env), ou reformulez la question."
        )
    import anthropic

    exemples = "\n\n".join(f"Question : {q}\nSPARQL : {s}" for q, s in EXEMPLES)
    systeme = SYSTEME.replace("{schema}", schema_en_texte()).replace("{exemples}", exemples)
    try:
        client = anthropic.Anthropic(api_key=settings.anthropic_key)
        rep = client.messages.create(
            model=settings.anthropic_model, max_tokens=1024, system=systeme,
            messages=[{"role": "user", "content": question}],
        )
    except Exception as exc:
        raise SmartGridError(f"Le service d'IA n'a pas répondu ({exc.__class__.__name__}). Réessayez plus tard.") from exc
    texte = "".join(b.text for b in rep.content if getattr(b, "type", "") == "text")
    return nettoyer(texte)


def repondre_avec_contexte(question: str, contexte: str, historique: list[dict] | None = None) -> str:
    """Formule une réponse en français à partir de faits extraits du graphe (RAG)."""
    if not disponible():
        raise SmartGridError("Assistant IA non configuré.")
    import anthropic

    systeme = (
        "Tu es l'Assistant SmartGrid. Réponds en français clair, sans jargon technique, uniquement à partir des "
        "FAITS fournis (extraits du graphe de connaissances). Si les faits ne permettent pas de répondre, dis-le. "
        "Cite les éléments utilisés entre guillemets français (« nom »)."
    )
    messages = list(historique or [])[-6:]
    messages.append({"role": "user", "content": f"FAITS :\n{contexte}\n\nQUESTION : {question}"})
    try:
        client = anthropic.Anthropic(api_key=settings.anthropic_key)
        rep = client.messages.create(model=settings.anthropic_model, max_tokens=800, system=systeme, messages=messages)
    except Exception as exc:
        raise SmartGridError(f"Le service d'IA n'a pas répondu ({exc.__class__.__name__}).") from exc
    return "".join(b.text for b in rep.content if getattr(b, "type", "") == "text").strip()
