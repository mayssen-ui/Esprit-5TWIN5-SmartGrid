"""Génère Fonctionnalites_avancees_IA.pdf (résumé court des fonctionnalités avancées et IA)."""
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

VERT = colors.HexColor("#1f6f5c")
st = getSampleStyleSheet()
cell = ParagraphStyle("c", parent=st["Normal"], fontSize=8.5, leading=11)
cellb = ParagraphStyle("cb", parent=cell, fontName="Helvetica-Bold")
head = ParagraphStyle("h", parent=cell, fontName="Helvetica-Bold", textColor=colors.white)

SECTIONS = [
    ("Traduction langage humain vers SPARQL (POST /api/nl2sparql) - sans LLM", [
        ("Outils TALN", "spaCy fr_core_news_md (tokenisation, lemmatisation, POS, dependances syntaxiques, NER, PhraseMatcher) et scikit-learn (TF-IDF + similarite cosinus). Aucune API de LLM."),
        ("Niveau 1 : analyse + regles", "Reperage des classes, proprietes et individus de l'ontologie sur les lemmes (FR/EN) ; intentions : liste, comptage, somme/moyenne/max/min, top N, valeur, relations (alimente par via l'arbre de dependances, batterie, proprietaires, noeuds), ajout, modification, suppression."),
        ("Niveau 2 : similarite", "Si aucune regle ne correspond : rapprochement TF-IDF avec les 17 requetes modeles du catalogue."),
        ("Niveau 3 : garde-fous", "Syntaxe validee par rdflib ; lecture libre limitee a SELECT/ASK/CONSTRUCT ; SERVICE, DROP, CLEAR, LOAD refuses ; INSERT/DELETE seulement apres confirmation et role admin ; LIMIT impose ; journal des traductions."),
        ("Interface", "Page 'Poser une question' : exemples cliquables, requete affichee, explication en francais, bouton 'Corriger la requete'."),
    ]),
    ("Intelligence artificielle", [
        ("Assistant SmartGrid", "Chatbot RAG : retrouve les faits dans le graphe par SPARQL, formule la reponse (phrases generees a partir des resultats) et cite les elements utilises."),
        ("Prevision", "Production solaire/eolienne : Holt-Winters saisonnier (statsmodels) ou foret aleatoire (scikit-learn), serie simulee ou CSV importe, bande d'incertitude, erreur MAE sur 24 h."),
        ("Detection d'anomalies", "IsolationForest ou z-score sur les series ; alertes sur l'etat du reseau (source a l'arret, saturee, consommation atypique, consommation superieure a la production)."),
        ("Recommandations", "Meilleure source pour un batiment non alimente : capacite restante 40 %, proximite du noeud 35 %, renouvelable 25 % ; detection des sources surchargees ; application en un clic."),
        ("Simulation 'et si'", "Ajout d'un batiment ou panne d'une source (avec bascule automatique) calcules sur une copie du graphe ; comparaison avant/apres du bilan."),
    ]),
    ("Web semantique et raisonnement", [
        ("Raisonneur HermiT", "Via owlready2 : coherence de l'ontologie, classes inferees (RenewableBuilding), liens deduits ; repli SPARQL si Java absent."),
        ("Etape 0 : schema", "Resume automatique des classes, hierarchie et proprietes (domaine/portee), utilise pour les formulaires dynamiques et la validation."),
        ("Requetes croisees", "17 requetes : FILTER, OPTIONAL, UNION, GROUP BY/HAVING, ORDER BY, sous-requetes, property path connectedTo+, VALUES, NOT EXISTS."),
        ("CRUD complexe", "Creation d'un batiment lie a source/noeud/batterie, reaffectation, suppression de source avec detachement, affectation multiple d'utilisateurs ; transactions avec rollback."),
    ]),
    ("Fonctionnalites avancees", [
        ("Statistiques", "9 graphiques Plotly et 11 indicateurs, tous par SPARQL agrege ; export CSV et PDF."),
        ("Graphe", "Visualisation pyvis coloree par categorie, filtres, clic sur un noeud pour ses proprietes."),
        ("Import / export", "RDF/XML, Turtle, JSON-LD, N-Triples, CSV par categorie ; import RDF ; import CSV en masse (tout ou rien)."),
        ("Editeur SPARQL", "Coloration syntaxique, export CSV/JSON des resultats, historique et favoris."),
        ("Securite par role", "Connexion liee a la classe User : admin (tout) et lecteur (lecture seule), sur l'interface et l'API (jetons signes, Swagger)."),
        ("Front et back", "Le front Streamlit (gestion CRUD, questions) appelle l'API REST FastAPI avec un jeton signe ; repli en mode direct si l'API est arretee."),
        ("Stockage", "rdflib en memoire avec sauvegarde du .owl apres chaque ecriture, ou Apache Jena Fuseki (docker-compose)."),
    ]),
]

doc = SimpleDocTemplate(str(Path(__file__).resolve().parent.parent / "Fonctionnalites_avancees_IA.pdf"), pagesize=A4,
                        leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36, title="SmartGrid - Fonctionnalites avancees et IA")
el = [Paragraph("SmartGrid Semantique", st["Title"]),
      Paragraph("Fonctionnalites avancees et intelligence artificielle", st["Heading2"]), Spacer(1, 6)]
for titre, lignes in SECTIONS:
    el.append(Paragraph(titre, ParagraphStyle("t", parent=st["Heading3"], textColor=VERT)))
    t = Table([[Paragraph("Fonction", head), Paragraph("Ce qui est fait", head)]] +
              [[Paragraph(a, cellb), Paragraph(b, cell)] for a, b in lignes], colWidths=[110, 413], repeatRows=1)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), VERT), ("GRID", (0, 0), (-1, -1), .4, colors.grey),
                           ("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f0f5f3")])]))
    el += [t, Spacer(1, 8)]
el.append(Paragraph("Limites : series de production simulees sans CSV ; mode Fuseki non teste de bout en bout.", cell))
doc.build(el)
print("ok")
