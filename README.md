# ⚡ SmartGrid Sémantique

Application web sémantique de gestion d'un **réseau électrique intelligent**, construite sur l'ontologie
OWL `SmartGrid-Semantic.owl` (créée avec Protégé) : CRUD complet, requêtes croisées, traduction
**langage humain → SPARQL**, statistiques, graphe, raisonnement HermiT, IA (prévision, anomalies,
recommandations, simulation, assistant).

* **Backend** : FastAPI + rdflib (SPARQL 1.1 Query et Update) — option Apache Jena Fuseki.
* **Frontend** : Streamlit multi-pages, entièrement en français, chaque bloc affiche sa requête SPARQL.
* **Raisonneur** : owlready2 + HermiT (Java requis).

## Architecture

```
┌──────────────────────┐        ┌───────────────────────────────┐
│  Streamlit (app/ui)  │        │  API REST FastAPI (app/api)   │  ← Swagger : /docs
│  11 pages, menu      │        │  /api/{classe}, /api/nl2sparql │
└──────────┬───────────┘        └───────────────┬───────────────┘
           │   mêmes services Python            │
           ▼                                    ▼
┌───────────────────────────────────────────────────────────────┐
│ app/services : crud · complex_ops · stats · reasoning · auth   │
│                io_service · history                            │
│ app/ai       : nlp · nl2sparql · guardrails · chatbot · forecast│
│                anomalies · recommend · simulation              │
│ app/sparql   : schema (Étape 0) · queries · store · prefixes   │
└───────────────────────────────┬───────────────────────────────┘
                                ▼
        SG_BACKEND=rdflib                    SG_BACKEND=fuseki
   graphe en mémoire + sauvegarde       Apache Jena Fuseki (TDB2)
   dans data/SmartGrid-Semantic.owl     (docker-compose.yml)
```

```
SmartGrid/
├── data/SmartGrid-Semantic.owl      ontologie mise à jour (User, individus) — compatible Protégé / HermiT
├── data/schema_summary.md|json      résumé du schéma généré automatiquement (Étape 0)
├── app/{api,services,sparql,ai,ui}  code
├── streamlit_app.py                 point d'entrée de l'interface
├── tests/                           80 tests pytest
├── requirements.txt · .env.example · docker-compose.yml
```

## Installation

Prérequis : Python 3.11+ (testé avec 3.14) et, pour le raisonnement HermiT, Java 11+.

```bash
python -m venv .venv
.venv\Scripts\activate          # Linux/macOS : source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env          # Linux/macOS : cp .env.example .env
```

## Lancement

```bash
uvicorn app.api.main:app --reload
```
API et documentation Swagger : <http://localhost:8000/docs>

```bash
streamlit run streamlit_app.py
```
Interface : <http://localhost:8501>

**Connexion** : les comptes sont les individus `User` de l'ontologie (rôle `hasRole`).
Mots de passe par défaut (modifiables dans `.env`) : `admin123` pour les administrateurs, `lecteur123` pour les lecteurs.

| Compte | Rôle |
|---|---|
| ahmed.bensalah@smartgrid.tn, leila.gharbi@smartgrid.tn | admin (tout) |
| salma.trabelsi@smartgrid.tn, karim.mansour@smartgrid.tn | lecteur (lecture seule) |

L'interface et l'API partagent le même fichier `.owl` : une modification faite d'un côté est vue de l'autre
(rechargement automatique si le fichier change). Une copie `data/SmartGrid-Semantic.owl.bak` du fichier d'origine est faite à la première écriture.

### Option Fuseki

```bash
docker compose up -d
```
puis dans `.env` : `SG_BACKEND=fuseki`. Au premier démarrage, l'ontologie est chargée dans Fuseki ; chaque écriture est
envoyée à Fuseki et exportée dans le `.owl`.

### Modèle de langue (obligatoire pour « Poser une question »)

Le module NLP utilise spaCy et son modèle français, installé par `pip install -r requirements.txt`. Si besoin :
`python -m spacy download fr_core_news_md`. Aucune clé d'API ni service externe n'est nécessaire.

### Communication front → back

Au démarrage, Streamlit teste si l'API répond sur `SG_API_URL` (défaut `http://localhost:8000`) :
* API démarrée : les pages **Gérer les éléments** et **Poser une question** passent par l'API REST (jeton obtenu à la connexion) ;
  la barre latérale affiche « Front → API REST ».
* API arrêtée : repli en mode direct (services Python), la barre latérale l'indique.
`SG_UI_MODE=api|direct|auto` force le mode. Lancez donc l'API **avant** Streamlit pour le mode complet.

## Étape 0 — schéma de l'ontologie

```bash
python -m app.sparql.schema
```
Lit le fichier OWL (rdflib) et écrit `data/schema_summary.md` / `.json` : classes, hiérarchie, propriétés avec domaine et portée.
Ce résumé sert à générer les formulaires dynamiques et la validation (`schema_en_texte()` en donne la version texte).

Modifications apportées à l'ontologie d'origine : classe `User` reliée par `owns` (→ Building) et `manages` (→ GridNode),
data properties `hasEmail` et `hasRole`, **4 utilisateurs**, `connectedTo` déclarée **symétrique**, et des individus supplémentaires
(≥ 3 par classe principale, dont une centrale à gaz non renouvelable et deux bâtiments non alimentés pour les recommandations).

## Les pages (captures décrites)

| Page | Ce que l'on voit |
|---|---|
| **Accueil** | Connexion par compte de l'ontologie, 8 cartes de métriques, guide des pages. |
| **Gérer les éléments** | Sélecteur de catégorie/type ; 4 onglets : tableau (recherche, filtre, tri, pagination) + fiche détail avec liens entrants/sortants ; formulaire d'ajout généré depuis le schéma ; modification préremplie ; suppression avec confirmation et cascade. |
| **Requêtes croisées** | 17 requêtes en langage humain (FILTER, OPTIONAL, UNION, GROUP BY/HAVING, ORDER BY, sous-requêtes, `connectedTo+`, VALUES…) + 4 opérations combinées transactionnelles. |
| **Poser une question** | Champ de texte, 8 exemples cliquables, phrase d'explication, tableau, requête affichée, bouton « Corriger la requête », confirmation obligatoire pour les modifications. |
| **Éditeur SPARQL** | Éditeur Ace avec coloration, export CSV/JSON, historique, favoris. |
| **Tableau de bord** | 11 indicateurs, 9 graphiques Plotly (barres, camemberts, courbe d'utilisation, bilans), export CSV et PDF. |
| **Graphe du réseau** | Graphe pyvis coloré par catégorie, filtres, clic sur un point = fiche de l'élément. |
| **Raisonnement** | Bouton « Lancer le raisonnement » : cohérence, `RenewableBuilding` inférés, liens déduits. |
| **Assistant SmartGrid** | Chat avec citation des éléments utilisés et requête consultable. |
| **Prévisions, alertes, simulation** | Courbe de prévision (Holt-Winters ou forêt aléatoire, import CSV), anomalies (IsolationForest / z-score), recommandations de source, simulation « et si ». |
| **Import / export** | RDF/XML, Turtle, JSON-LD, N-Triples, CSV par catégorie, import RDF, import CSV en masse (tout ou rien). |

## Exemples de phrases (page « Poser une question » ou `POST /api/nl2sparql`)

* Citer les différents bâtiments
* Quels bâtiments sont alimentés par une ferme solaire ?
* Citer les bâtiments alimentés par une source d'énergie renouvelable
* Combien de sources éoliennes y a-t-il ? / How many wind sources are there?
* Quelle est la consommation totale des bâtiments industriels ?
* Quelle est la capacité de la batterie Tunis 01 ?
* Top 3 des plus gros consommateurs
* Quels utilisateurs possèdent des bâtiments industriels ?
* Quelles sources ont une capacité supérieure à 40 ?
* Ajouter une batterie nommée Batterie Sousse de capacité 12 *(confirmation requise)*
* Modifier la capacité de la batterie Batterie Tunis 01 à 15 *(confirmation requise)*
* Supprimer le bâtiment ESPRIT *(confirmation requise)*

```bash
curl -X POST http://localhost:8000/api/nl2sparql -H "Authorization: Bearer <jeton>" -H "Content-Type: application/json" \
     -d "{\"question\": \"Combien de sources éoliennes y a-t-il ?\"}"
```
Réponse : `sparql`, `resultat`, `explication`, `message` (phrase), `niveau` (`regles`/`similarite`/`edite`), `confirmation_requise`.

**Stratégie en 3 niveaux (traitement du langage avec spaCy et scikit-learn, sans LLM)** :
(a) analyse linguistique et règles : voir « Module NLP » ci-dessous ; (b) à défaut, rapprochement TF-IDF avec les requêtes modèles du catalogue ;
(c) garde-fous : syntaxe validée par rdflib, lecture libre limitée à SELECT/ASK/CONSTRUCT, `SERVICE`/`DROP`/`CLEAR`/`LOAD` refusés,
INSERT/DELETE exécutés seulement avec `confirm: true` et rôle admin, `LIMIT` imposé (`SG_MAX_RESULTS`), journal dans `data/logs/nl2sparql.jsonl`.

## Module NLP / TALN (langage naturel → SPARQL)

Conformément au sujet, la traduction n'utilise **aucun LLM ni API de génération** (ni Gemini, ni OpenAI, ni Claude) :
elle est développée avec des bibliothèques de TALN.

| Outil | Rôle dans le projet | Fichier |
|---|---|---|
| **spaCy** `fr_core_news_md` : tokenisation | découpe la phrase | `app/ai/nlp.py` |
| spaCy : **lemmatisation** | « alimentés » → *alimenter*, « sources éoliennes » → *source éolienne* : pluriels et conjugaisons gérés | `nlp.analyser` |
| spaCy : **étiquetage grammatical (POS)** | catégories des mots (verbe, nom, nombre…) | `Analyse.pos` |
| spaCy : **analyse en dépendances** | extrait le complément d'agent de « alimenté **par** une ferme solaire » | `nlp.complement_agent` |
| spaCy : **reconnaissance d'entités nommées** | repère les lieux (ex. Tunis) | `Analyse.entites` |
| spaCy **PhraseMatcher** (sur les lemmes) | repère les classes, propriétés et individus de l'ontologie (dictionnaire de synonymes FR/EN) | `nlp.Repereur`, `vocab.py` |
| **scikit-learn** `TfidfVectorizer` + similarité cosinus | si aucune règle ne s'applique, rattache la question à la requête modèle la plus proche (17 requêtes du catalogue) | `nlp.Similarite` |
| rdflib | validation syntaxique des requêtes générées | `guardrails.py` |

Chaîne de traitement : phrase → analyse spaCy → repérage des entités de l'ontologie → détection de l'intention (liste, comptage, agrégat,
top N, valeur, relation, ajout, modification, suppression) → génération du SPARQL (modèles) → garde-fous → exécution → phrase de réponse.
Si l'intention n'est pas reconnue : similarité TF-IDF (seuil 0,30) avec les requêtes modèles, sinon message d'aide.

## API REST

`GET/POST /api/{classe}`, `GET/PUT/DELETE /api/{classe}/{id}` (ex. `/api/SolarSource`, casse libre ; `DELETE …?cascade=true`),
plus `/api/requetes`, `/api/operations/*`, `/api/stats`, `/api/raisonnement`, `/api/ia/*`, `/api/export/{format}`, `/api/import/*`,
`/api/sparql/query|update`. Authentification : bouton **Authorize** de Swagger (e-mail + mot de passe). `SG_API_AUTH=false` la désactive.
Codes d'erreur : 401 (non connecté), 403 (lecteur), 404 (inconnu), 409 (élément référencé), 422 (valeurs invalides).

## Tests

```bash
pytest
```
80 tests : CRUD et validation, CRUD complexe et rollback, 17 requêtes croisées, NL→SPARQL et garde-fous, statistiques, IA, HermiT,
import/export, API et rôles, module NLP (lemmes, dépendances, similarité), chargement de chaque page Streamlit. Chaque test travaille sur une copie jetable de l'ontologie.

## Limites connues

* Les unités affichées (MW, MWh, kV) sont des indications : l'ontologie ne les précise pas.
* Les séries de production sont **simulées** (déterministes) tant qu'aucun CSV n'est importé.
* Le mode Fuseki n'a pas été testé de bout en bout (Docker non lancé pendant le développement).
* Les mots de passe sont communs à chaque rôle (authentification de démonstration, à renforcer en production).
* Le fichier `.owl` est réécrit par rdflib (RDF/XML valide pour Protégé, mais mise en forme différente de l'original).

## Checklist des exigences

| Exigence | État | Où |
|---|---|---|
| ≥ 12 classes (20 avec classes définies) + User, owns, manages, hasEmail, hasRole, 4 utilisateurs | ✅ | `data/SmartGrid-Semantic.owl` |
| Étape 0 : résumé automatique du schéma | ✅ | `app/sparql/schema.py`, `data/schema_summary.*` |
| FastAPI + rdflib (SPARQL Query/Update), option Fuseki + docker-compose, persistance après écriture | ✅ (Fuseki non testé) | `app/sparql/store.py`, `docker-compose.yml` |
| Streamlit multi-pages, menu latéral, design propre | ✅ | `streamlit_app.py`, `app/ui/pages/` |
| Raisonnement HermiT + bouton + inférences + cohérence | ✅ | `app/services/reasoning.py`, page *Raisonnement* |
| Langage humain partout + expander « Voir la requête SPARQL » | ✅ | `app/ui/common.py` |
| CRUD complet (Create/Read/Update/Delete, validation XSD, intégrité, cascade, URI uniques) | ✅ | `app/services/crud.py`, page *Gérer les éléments* |
| API REST `/api/{classe}` + Swagger | ✅ | `app/api/` |
| Requêtes croisées (8 cas obligatoires + FILTER/OPTIONAL/UNION/GROUP BY/HAVING/ORDER BY/sous-requêtes/property path/VALUES) | ✅ | `app/sparql/queries.py` |
| CRUD complexe transactionnel (rollback, réaffectation, suppression avec détachement, affectation multiple) | ✅ | `app/services/complex_ops.py` |
| Module NLP/TALN sans LLM (spaCy, scikit-learn) : `POST /api/nl2sparql` + garde-fous + page + « Corriger la requête » | ✅ | `app/ai/nlp.py`, `nl2sparql.py`, `vocab.py`, `guardrails.py` |
| Communication front ↔ back (Streamlit via l'API REST) | ✅ (gestion CRUD et questions ; les autres pages utilisent les services directement) | `app/ui/backend.py` |
| Statistiques SPARQL agrégées, graphiques Plotly, KPI, export CSV/PDF | ✅ | `app/services/stats.py`, page *Tableau de bord* |
| Graphe pyvis (couleurs, filtres, clic) | ✅ | page *Graphe du réseau* |
| Chatbot RAG avec citations | ✅ | `app/ai/chatbot.py` |
| Prévision (statsmodels / scikit-learn, CSV) | ✅ | `app/ai/forecast.py` |
| Détection d'anomalies (IsolationForest / z-score) + alertes | ✅ | `app/ai/anomalies.py` |
| Recommandations + sources surchargées | ✅ | `app/ai/recommend.py` |
| Simulation « et si » | ✅ | `app/ai/simulation.py` |
| Import/export RDF/XML, Turtle, JSON-LD, CSV, import en masse | ✅ | `app/services/io_service.py` |
| Historique, favoris, éditeur SPARQL coloré | ✅ | `app/services/history.py`, page *Éditeur SPARQL* |
| Authentification par rôle liée à `User` | ✅ | `app/services/auth.py`, `app/api/deps.py` |
| Tests pytest (CRUD, NL→SPARQL, statistiques) | ✅ 80 tests | `tests/` |

## L'ontologie en bref

* **Espace de noms** : `http://www.semanticweb.org/smartgrid-semantic#` (préfixe `sg:`).
* **Classes** : `EnergySource` (`SolarSource`, `WindSource`), `EnergyStorage` (`BatteryStorage`), `Building` (`ResidentialBuilding`,
  `CommercialBuilding`, `IndustrialBuilding`), `GridElement` (`GridNode`, `Substation`), `Energy` (`RenewableEnergy`, `NonRenewableEnergy`),
  `User`, et les classes définies `RenewableEnergySource` et `RenewableBuilding`.
* **Relations** : `produces`, `consumes`, `storesEnergy`, `connectedTo` (symétrique), `suppliedBy`, `locatedIn`, `contains`, `hasStorage`,
  `hasSource`, `feeds`, `owns`, `manages`.
* **Données** : `hasName`, `hasCapacity`, `hasPowerOutput`, `hasConsumption`, `hasStorageCapacity`, `hasEfficiency`, `hasVoltage`,
  `hasLocation`, `hasInstallationDate`, `hasEmail`, `hasRole`.
* Les sous-classes sont interrogées avec `?x a/rdfs:subClassOf* sg:Classe` (rdflib n'infère pas) ; le raisonneur HermiT calcule les classes définies.

## Variables d'environnement (`.env`)

| Variable | Rôle | Défaut |
|---|---|---|
| `SG_BACKEND` | `rdflib` ou `fuseki` | `rdflib` |
| `SG_OWL_PATH` | fichier d'ontologie | `data/SmartGrid-Semantic.owl` |
| `FUSEKI_URL`, `FUSEKI_DATASET` | serveur Fuseki | `http://localhost:3030`, `smartgrid` |
| `SG_UI_MODE`, `SG_API_URL` | mode du front (`auto`/`api`/`direct`) et adresse de l'API | `auto`, `http://localhost:8000` |
| `SG_ADMIN_PASSWORD`, `SG_READER_PASSWORD` | mots de passe des rôles | `admin123`, `lecteur123` |
| `SG_API_AUTH`, `SG_SECRET_KEY` | authentification de l'API | `true`, `changez-moi` |
| `SG_MAX_RESULTS` | plafond de résultats | `500` |
| `SG_DATA_DIR` | dossier de l'historique et des journaux | `data` |

## Scénario de test manuel rapide

1. Connexion `ahmed.bensalah@smartgrid.tn` / `admin123` : 9 bâtiments, 6 sources sur l'accueil.
2. *Gérer les éléments* : créer une source avec production > capacité (erreur claire), corriger, puis supprimer une source référencée (cascade demandée).
3. *Requêtes croisées* : « consommation supérieure à la production » → Usine Ariana 01 ; opération combinée avec valeur invalide → retour en arrière.
4. *Poser une question* : « Combien de sources éoliennes y a-t-il ? » → 2 ; un ajout demande confirmation ; `DROP ALL` est refusé.
5. *Raisonnement* : cohérent, 6 `RenewableBuilding` déduits.
6. *Prévisions, alertes, simulation* : prévision, anomalies, recommandation pour Maison Sousse 01, panne de `SolarFarm_Ariana`.
7. Connexion `salma.trabelsi@smartgrid.tn` / `lecteur123` : écriture refusée (lecture seule).
8. API : <http://localhost:8000/docs> → Authorize → `POST /api/nl2sparql`.

## Dépannage

* **HermiT indisponible** : installer Java 11+ (`java -version`) ; sinon l'application utilise un calcul SPARQL simplifié.
* **Fuseki injoignable** : `docker compose up -d`, vérifier `FUSEKI_URL`.
* **Modification externe du `.owl`** (Protégé) : l'application recharge le fichier automatiquement à la requête suivante.
* **Revenir à l'ontologie d'origine** : restaurer `data/SmartGrid-Semantic.owl.bak`.

## Documents complémentaires

* `Fonctionnalites_avancees_IA.pdf` : résumé d'une page des fonctions avancées et d'IA (généré par `docs/generer_pdf.py`).
* `data/schema_summary.md` : résumé du schéma généré à l'étape 0.
