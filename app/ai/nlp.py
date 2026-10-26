"""Traitement automatique du langage (TALN) avec spaCy et scikit-learn.

Outils utilisés (aucun LLM, aucun appel à une API externe) :
  * spaCy `fr_core_news_md` : tokenisation, lemmatisation, étiquetage grammatical (POS), analyse en
    dépendances syntaxiques, reconnaissance d'entités nommées (NER) ;
  * spaCy `PhraseMatcher` : repérage des classes, propriétés et individus de l'ontologie dans la phrase
    (sur les lemmes, donc insensible aux pluriels et aux conjugaisons) ;
  * scikit-learn `TfidfVectorizer` + similarité cosinus : rapprochement d'une question inconnue
    des requêtes modèles du catalogue.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache

from app.errors import SmartGridError

MODELES = ("fr_core_news_md", "fr_core_news_sm", "fr_core_news_lg")


@lru_cache(maxsize=1)
def get_nlp():
    """Charge le modèle spaCy français (installé avec `pip install -r requirements.txt`)."""
    import spacy

    for nom in MODELES:
        try:
            return spacy.load(nom)
        except OSError:
            continue
    raise SmartGridError(
        "Le modèle de langue français de spaCy n'est pas installé. Lancez : "
        "python -m spacy download fr_core_news_md")


def sans_accents(texte: str) -> str:
    s = unicodedata.normalize("NFD", texte)
    return "".join(c for c in s if unicodedata.category(c) != "Mn").lower().replace("œ", "oe")


@dataclass
class Analyse:
    """Résultat de l'analyse linguistique d'une phrase."""

    texte: str
    doc: object
    lemmes: set[str] = field(default_factory=set)     # lemmes et formes, sans accents, en minuscules
    nombres: list[float] = field(default_factory=list)
    entites: list[tuple[str, str]] = field(default_factory=list)   # (texte, type NER)
    pos: list[tuple[str, str, str]] = field(default_factory=list)  # (mot, lemme, catégorie)

    def a(self, *mots: str) -> bool:
        """Vrai si l'un des mots (ou lemmes) est présent dans la phrase."""
        return any(sans_accents(m) in self.lemmes for m in mots)


def analyser(texte: str) -> Analyse:
    doc = get_nlp()(texte)
    lemmes: set[str] = set()
    nombres: list[float] = []
    for t in doc:
        lemmes.add(sans_accents(t.lemma_))
        lemmes.add(sans_accents(t.text))
        if t.like_num:
            try:
                nombres.append(float(t.text.replace(",", ".")))
            except ValueError:
                pass
    return Analyse(texte, doc, lemmes, nombres, [(e.text, e.label_) for e in doc.ents],
                   [(t.text, t.lemma_, t.pos_) for t in doc])


# --------------------------------------------------------------------------------------------
# Repérage des termes de l'ontologie (PhraseMatcher sur les lemmes)
# --------------------------------------------------------------------------------------------
class Repereur:
    """Associe des expressions (« source solaire », « consommation »…) à des clés de l'ontologie."""

    def __init__(self, synonymes: dict[str, list[str]]):
        from spacy.matcher import PhraseMatcher

        nlp = get_nlp()
        self.lemme = PhraseMatcher(nlp.vocab, attr="LEMMA")
        self.forme = PhraseMatcher(nlp.vocab, attr="LOWER")
        self.cles: dict[str, str] = {}
        for cle, expressions in synonymes.items():
            for expr in expressions:
                doc = nlp(expr)
                ident = f"{cle}::{expr}"
                self.cles[ident] = cle
                self.lemme.add(ident, [doc])
                self.forme.add(ident, [nlp.make_doc(expr)])

    def trouver(self, analyse: Analyse) -> list[tuple[str, int, int]]:
        """(clé, début, fin) en caractères ; en cas de chevauchement, l'expression la plus longue gagne."""
        doc = analyse.doc
        candidats = []
        for matcher in (self.lemme, self.forme):
            for ident, d, f in matcher(doc):
                nom = doc.vocab.strings[ident]
                span = doc[d:f]
                candidats.append((self.cles[nom], span.start_char, span.end_char))
        candidats.sort(key=lambda c: (-(c[2] - c[1]), c[1]))
        pris: list[tuple[str, int, int]] = []
        for cle, d, f in candidats:
            if all(f <= d2 or d >= f2 for _, d2, f2 in pris):
                pris.append((cle, d, f))
        return sorted(pris, key=lambda x: x[1])


# --------------------------------------------------------------------------------------------
# Dépendances syntaxiques : complément d'agent « alimenté PAR … »
# --------------------------------------------------------------------------------------------
VERBES_ALIMENTATION = {"alimenter", "fournir", "approvisionner", "supply", "power"}


def complement_agent(analyse: Analyse) -> tuple[int, int] | None:
    """Positions (en caractères) du groupe nominal introduit par « par » après un verbe d'alimentation.

    S'appuie sur l'arbre de dépendances : on cherche la préposition « par » (relation `case`) dont la tête
    dépend d'un verbe comme « alimenter », puis on retourne le sous-arbre de cette tête.
    """
    doc = analyse.doc
    for tok in doc:
        if tok.lower_ in ("par", "by") and tok.dep_ == "case":
            tete = tok.head
            ancetre = tete.head
            if sans_accents(ancetre.lemma_) in VERBES_ALIMENTATION or sans_accents(tete.head.lemma_) in VERBES_ALIMENTATION \
                    or any(sans_accents(a.lemma_) in VERBES_ALIMENTATION for a in tete.ancestors):
                sous_arbre = list(tete.subtree)
                return sous_arbre[0].idx, sous_arbre[-1].idx + len(sous_arbre[-1].text)
    return None


# --------------------------------------------------------------------------------------------
# Similarité TF-IDF avec les requêtes modèles
# --------------------------------------------------------------------------------------------
STOP = {"le", "la", "les", "l", "un", "une", "des", "du", "de", "d", "et", "ou", "a", "au", "aux", "en", "dans",
        "sur", "par", "pour", "qui", "que", "quel", "quelle", "etre", "avoir", "est", "sont"}


def _lemmes_texte(texte: str) -> str:
    doc = get_nlp()(texte)
    mots = [sans_accents(t.lemma_) for t in doc if not t.is_punct and not t.is_space]
    return " ".join(m for m in mots if m not in STOP)


class Similarite:
    """Cherche, parmi une liste de phrases modèles, celle qui ressemble le plus à la question."""

    def __init__(self, modeles: list[tuple[str, str]]):
        from sklearn.feature_extraction.text import TfidfVectorizer

        self.ids = [i for i, _ in modeles]
        self.vec = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True)
        self.matrice = self.vec.fit_transform([_lemmes_texte(t) for _, t in modeles])

    def meilleur(self, question: str, seuil: float = 0.30) -> tuple[str, float] | None:
        from sklearn.metrics.pairwise import cosine_similarity

        scores = cosine_similarity(self.vec.transform([_lemmes_texte(question)]), self.matrice)[0]
        i = int(scores.argmax())
        return (self.ids[i], float(scores[i])) if scores[i] >= seuil else None
