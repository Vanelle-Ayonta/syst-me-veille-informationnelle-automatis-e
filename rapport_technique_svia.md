# Rapport Technique — Système de Veille Informationnelle Automatisée (SVIA)
## DIIF / Banque des États de l'Afrique Centrale (BEAC)

---

## Table des matières

1. [Architecture générale](#1-architecture-générale)
2. [Pipeline de scraping](#2-pipeline-de-scraping)
3. [Moteur RAG](#3-moteur-rag)
4. [Agent pydantic-ai](#4-agent-pydantic-ai)
5. [Interface Streamlit](#5-interface-streamlit)
6. [Déploiement Docker](#6-déploiement-docker)
7. [Tests et CI/CD](#7-tests-et-cicd)

---

## 1. Architecture générale

### 1.1 Vue d'ensemble

Le SVIA (Système de Veille Informationnelle Automatisée) est une application full-stack Python conçue pour le Département de l'Inclusion et de l'Innovation Financières (DIIF) de la BEAC. Il automatise la collecte, l'indexation et l'analyse de publications institutionnelles portant sur l'inclusion financière et l'innovation financière en zone CEMAC et dans le monde.

Le système repose sur quatre couches fonctionnelles indépendantes et orchestrées :

```
┌──────────────────────────────────────────────────────────────────┐
│                     INTERFACE STREAMLIT                          │
│         (authentification JWT, 10 pages, export Word/PDF)        │
└──────────────────────────┬───────────────────────────────────────┘
                           │
┌──────────────────────────▼───────────────────────────────────────┐
│                      AGENT SVIA                                  │
│         (pydantic-ai, 5 outils, guardrails 4 niveaux)            │
└──────────┬──────────────────────────────────────┬────────────────┘
           │                                      │
┌──────────▼──────────────┐       ┌───────────────▼────────────────┐
│     MOTEUR RAG          │       │     BASE DE DONNÉES SQLite      │
│  (FAISS + e5-base)      │       │     (veille_diif.db, WAL)       │
└─────────────────────────┘       └───────────────┬────────────────┘
                                                  │
                                  ┌───────────────▼────────────────┐
                                  │     PIPELINE DE SCRAPING        │
                                  │  (22 sources, 5 workers,        │
                                  │   ThreadPoolExecutor)           │
                                  └────────────────────────────────┘
```

### 1.2 Structure des dossiers

```
veille_diif1/
│
├── app.py                    # Point d'entrée Streamlit (SPA, routage, CSS)
├── config.py                 # Configuration centralisée (env vars, constantes)
├── init_db.py                # Initialisation schéma SQLite (tables, données seed)
├── requirements.txt          # Dépendances Python épinglées
├── Dockerfile                # Image autonome (torch + modèle embarqués)
├── docker-compose.yml        # Service unique avec volume data/
│
├── agents/
│   └── svia_agent.py         # Agent conversationnel pydantic-ai (629 lignes)
│
├── core/
│   ├── auth.py               # JWT, bcrypt, réinitialisation mot de passe
│   ├── database.py           # CRUD SQLite, context manager, statistiques
│   ├── document_processor.py # Extraction texte PDF/DOCX/TXT
│   ├── export.py             # Rapports Word/PDF, envoi email SMTP
│   ├── guardrails.py         # Filtres sécurité (injection, confidentialité…)
│   ├── schemas.py            # Modèles Pydantic partagés
│   ├── scheduler.py          # Planificateur collecte automatique (threading)
│   └── rag/
│       ├── embedder.py       # Modèle sentence-transformers (singleton)
│       ├── chunker.py        # Découpage articles, filtrage thématique
│       ├── indexer.py        # Index FAISS (création, mise à jour, sauvegarde)
│       ├── retriever.py      # Recherche sémantique L2, filtres post-recherche
│       ├── pipeline.py       # Orchestrateur chunking + indexation
│       └── run_pipeline.py   # Script CLI autonome (rebuild complet)
│
├── scrapers/
│   ├── base_scraper.py              # Fonctions communes (CRUD, déduplication)
│   ├── cleaner.py                   # Nettoyage texte HTML, normalisation
│   ├── scraper_all.py               # Orchestrateur parallèle (22 sources)
│   ├── scraper_dba.py               # Digital Business Africa (RSS + web)
│   ├── scraper_findev.py            # FinDev Gateway (web paginé)
│   ├── scraper_afi.py               # AFI Global (WordPress API + web)
│   ├── scraper_gsma.py              # GSMA (web)
│   ├── scraper_cnef.py              # CNEF Cameroun (WordPress API)
│   ├── scraper_bdf.py               # Banque de France (web)
│   ├── scraper_bis.py               # BRI (web + RSS)
│   ├── scraper_gimac.py             # GIMAC (web)
│   ├── scraper_lfpt.py              # La Finance pour Tous (web)
│   ├── scraper_playwright_banks.py  # Banque du Canada (Playwright)
│   ├── scraper_wp_banks.py          # CBK Kenya (WordPress API)
│   ├── scraper_bceao.py             # BCEAO (web)
│   ├── scraper_bkam.py              # Bank Al-Maghrib (web)
│   ├── scraper_cbn_bnr.py           # CBN Nigeria + BNR Rwanda (web)
│   └── scraper_intl.py              # 7 sources internationales (RSS + web)
│
├── ui/
│   ├── components/
│   │   └── header.py          # Bande supérieure fixe (logo BEAC, date)
│   └── pages/
│       ├── login.py           # Authentification (login, reset mdp)
│       ├── dashboard.py       # Tableau de bord (métriques, graphiques)
│       ├── veille.py          # Consultation articles, upload, collecte
│       ├── chatbot.py         # Interface conversationnelle SVIA
│       ├── export.py          # Génération Word/PDF, envoi email
│       ├── admin.py           # Administration système
│       ├── gestion_sources.py # CRUD sources de veille
│       ├── gestion_utilisateurs.py  # CRUD utilisateurs
│       ├── logs.py            # Audit trail
│       ├── nuage.py           # Nuages de mots FR/EN
│       └── suggestions_page.py  # Recommandations DIIF
│
├── assets/
│   └── logo_beac.png          # Logo institutionnel
│
├── data/                      # Hors image Docker (volume monté)
│   ├── veille_diif.db         # Base SQLite principale
│   ├── faiss_index.bin        # Index vectoriel FAISS
│   ├── faiss_index_ids.npy    # Mapping chunk_id ↔ faiss_id
│   ├── uploads/               # Documents uploadés
│   ├── exports/               # Rapports générés
│   └── backups/               # Sauvegardes
│
└── .github/workflows/
    ├── ci.yml                 # Lint + tests pytest
    └── docker.yml             # Build et push image GHCR
```

### 1.3 Stack technique

| Couche | Technologie | Version |
|--------|------------|---------|
| **Langage** | Python | 3.11 |
| **Interface web** | Streamlit | 1.56.0 |
| **Agent IA** | pydantic-ai[anthropic] | 1.105.0 |
| **LLM principal** | Anthropic Claude Sonnet | claude-sonnet-4-5 |
| **LLM rapide** | Anthropic Claude Haiku | claude-haiku-4-5-20251001 |
| **LLM alternatif** | OpenAI GPT-4o / GPT-4o-mini | — |
| **Embeddings** | sentence-transformers | 5.4.1 |
| **Modèle embedding** | intfloat/multilingual-e5-base | — |
| **Index vectoriel** | faiss-cpu | ≥1.7.4 |
| **Base de données** | SQLite (WAL mode) | 3.x (stdlib) |
| **Scraping statique** | BeautifulSoup4 + requests | ≥4.12.0 / ≥2.31.0 |
| **Scraping dynamique** | Playwright (via subprocess) | — |
| **Parsing RSS/Atom** | feedparser | ≥6.0.0 |
| **Deep learning** | PyTorch CPU | 2.6.0+cpu |
| **Transformers** | transformers + tokenizers | 5.5.4 / 0.22.2 |
| **Export Word** | python-docx | ≥0.8.11 |
| **Export PDF** | ReportLab | ≥4.0.0 |
| **Graphiques** | Plotly | ≥6.0.0 |
| **Nuages de mots** | wordcloud + matplotlib | ≥1.9.0 / ≥3.7.0 |
| **Auth** | bcrypt + PyJWT | ≥4.0.0 / ≥2.8.0 |
| **Modèles données** | Pydantic | 2.13.1 |
| **Conteneur** | Docker (python:3.11-slim) | — |
| **Orchestration** | docker-compose | — |
| **CI/CD** | GitHub Actions | — |

### 1.4 Schéma des dépendances entre modules

```
config.py ──────────────────────────────────────────────────────────────────┐
     │                                                                       │
     ├──► core/database.py ◄──── scrapers/base_scraper.py                   │
     │         │                         │                                   │
     │         │              scrapers/cleaner.py                            │
     │         │              scrapers/scraper_*.py                          │
     │         │              scrapers/scraper_all.py (orchestre tout)       │
     │         │                                                             │
     ├──► core/rag/embedder.py ──────────────────────┐                       │
     │         │                                     │                       │
     │    core/rag/chunker.py ◄── database.py        │                       │
     │         │                                     │                       │
     │    core/rag/indexer.py ◄── embedder.py        │                       │
     │         │                                     │                       │
     │    core/rag/retriever.py ◄─ indexer + embedder│                       │
     │         │                                     │                       │
     │    core/rag/pipeline.py ◄─ chunker + indexer  │                       │
     │                                               │                       │
     ├──► agents/svia_agent.py ◄── retriever + guardrails + database        │
     │                                                                       │
     ├──► core/auth.py ◄── database.py                                       │
     │                                                                       │
     ├──► core/export.py ◄── database.py + anthropic API                    │
     │                                                                       │
     ├──► core/scheduler.py ◄── scraper_all.py (subprocess)                 │
     │                                                                       │
     └──► app.py ◄── auth + scheduler + ui/pages/* ◄──────────────────────┘
```

### 1.5 Flux de données global

```
COLLECTE          STOCKAGE           INDEXATION         REQUÊTE
─────────         ─────────          ──────────         ────────
22 sources    →   SQLite             Chunker        →   Embedder
(RSS/Web/API)     veille_diif.db  →  (1600 chars)       (e5-base)
5 workers                            ↓                  ↓
ThreadPool        articles +         Indexer        →   FAISS
subprocess        chunks +        →  FAISS .bin         L2 search
isolation         sources            _ids.npy           ↓
                                                        Retriever
                                                        (top-k)
                                                        ↓
                                                   AGENT SVIA
                                                   (pydantic-ai)
                                                   Claude Sonnet
                                                        ↓
                                                   GUARDRAILS
                                                   (4 niveaux)
                                                        ↓
                                                   STREAMLIT UI
                                                   (streaming
                                                    token/token)
```

---

## 2. Pipeline de scraping

### 2.1 Liste exhaustive des 22 sources

| # | Source | URL | Catégorie | Langue | Méthode |
|---|--------|-----|-----------|--------|---------|
| 1 | Digital Business Africa | digitalbusiness.africa | Innovation/Tech Afrique | FR | BS4 + RSS |
| 2 | FinDev Gateway | findevgateway.org | Recherche IF mondiale | EN | BS4 paginé |
| 3 | AFI Global | afi-global.org | Inclusion financière mondiale | EN | WP API + BS4 |
| 4 | GSMA | gsma.com | Mobile money / télécoms | EN | BS4 paginé |
| 5 | CNEF Cameroun | cnefcameroun.cm | Inclusion financière CEMAC | FR | WP API |
| 6 | Banque de France | banque-france.fr | Banque centrale FR | FR | BS4 paginé |
| 7 | BRI (BIS) | bis.org | Banque des règlements int. | EN | BS4 + RSS |
| 8 | GIMAC | gimac-afr.com | Paiements CEMAC | FR | BS4 |
| 9 | La Finance pour Tous | lafinancepourtous.com | Éducation financière | FR | BS4 |
| 10 | Banque du Canada | bankofcanada.ca | Banque centrale — CBDC/Fintech | EN | Playwright |
| 11 | Central Bank of Kenya | centralbank.go.ke | Banque centrale — mobile money | EN | WP API + BS4 |
| 12 | BCEAO | bceao.int | Banque centrale Afrique Ouest | FR | BS4 |
| 13 | Bank Al-Maghrib (BKAM) | bkam.ma | Banque centrale Maroc | FR | BS4 |
| 14 | Central Bank of Nigeria | cbn.gov.ng | Banque centrale Nigeria | EN | BS4 |
| 15 | National Bank of Rwanda | bnr.rw | Banque centrale Rwanda | EN | BS4 |
| 16 | Banque mondiale | blogs.worldbank.org | Développement / IF mondiale | EN | RSS (4 flux) |
| 17 | CGAP | cgap.org | Microfinance mondiale | EN | RSS + BS4 |
| 18 | Women's World Banking | womensworldbanking.org | IF genre / femmes | EN | RSS WP |
| 19 | Better Than Cash Alliance | betterthancash.org | Paiements numériques | EN | BS4 paginé |
| 20 | Center for Financial Inclusion | centerforfinancialinclusion.org | IF mondiale | EN | BS4 |
| 21 | ADA Luxembourg | adaimpact.lu | Microfinance / impact | FR | BS4 paginé |
| 22 | AFD | afd.fr | Développement / finance | FR | BS4 paginé |

### 2.2 Méthodes de scraping par source

**BeautifulSoup4 + requests (méthode principale — 20 sources)**

Utilisée pour les sites à contenu HTML statique ou serveur-side rendered. Le pipeline par source suit un schéma uniforme :

1. Requête HTTP avec headers User-Agent simulant un navigateur réel
2. Parsing HTML avec `BeautifulSoup(r.text, "html.parser")`
3. Extraction des liens d'articles (sélecteurs CSS ou attributs `href`)
4. Récupération et parsing de chaque article individuellement
5. Appel `sauvegarder_article()` avec déduplication par URL

Pour les sources basées sur WordPress, l'API REST (`/wp-json/wp/v2/posts`) est utilisée en priorité ; le scraping HTML classique sert de fallback.

Pour les sources avec flux RSS/Atom (Banque mondiale, WWB, CGAP, DBA, BIS), `feedparser` parse le XML et extrait titre, résumé, lien et date de publication.

**Playwright (1 source — Banque du Canada)**

La Banque du Canada charge ses publications via JavaScript (rendu côté client). Un script Playwright en mode headless est lancé en subprocess isolé. Cette isolation garantit qu'un crash Playwright ne perturbe pas les autres workers.

### 2.3 Gestion des dates

Chaque article collecté reçoit deux horodatages :

- `publie_le` : date de publication extraite depuis le site source (format ISO 8601 normalisé). Peut être `NULL` si absente.
- `collecte_le` : horodatage UTC de la collecte (`datetime.utcnow().isoformat()`), toujours présent.

Le paramètre `--depuis YYYY-MM-DD` (disponible dans `scraper_all.py` et chaque scraper individuel) filtre les articles antérieurs à la date spécifiée, évitant la ré-ingestion de l'historique lors des collectes incrémentales.

### 2.4 Déduplication

La déduplication est globale, sur l'URL canonique de chaque article :

```python
def url_existe(url: str) -> bool:
    with get_db() as conn:
        return conn.execute(
            "SELECT id FROM articles WHERE url_original = ?", (url,)
        ).fetchone() is not None
```

Cette vérification est effectuée dans `sauvegarder_article()` avant tout traitement ou insertion. Elle protège contre les doublons entre scrapers et entre exécutions successives.

### 2.5 Stockage SQLite

La base `veille_diif.db` utilise le mode WAL (Write-Ahead Logging) pour permettre les écritures concurrentes de plusieurs scrapers en parallèle sans corruption de données :

```sql
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA busy_timeout = 5000;
PRAGMA foreign_keys = ON;
```

Le schéma principal (table `articles`) stocke :

| Colonne | Type | Description |
|---------|------|-------------|
| `id` | TEXT (UUID) | Identifiant unique |
| `source_id` | TEXT (FK) | Source d'origine |
| `titre` | TEXT | Titre de l'article (max 500 chars) |
| `contenu` | TEXT | Texte nettoyé (max 6000 chars) |
| `resume` | TEXT | Résumé (max 1000 chars) |
| `url_original` | TEXT (UNIQUE) | URL canonique |
| `publie_le` | TEXT | Date publication ISO |
| `collecte_le` | TEXT | Horodatage collecte UTC |
| `langue` | TEXT | `fr` ou `en` |
| `qualite_contenu` | TEXT | `complet` / `partiel` / `resume` / `hors_perimetre` |
| `est_doublon` | INTEGER | Flag déduplication |
| `indexe` | INTEGER | 0 = pas encore indexé FAISS |

La qualité du contenu est évaluée automatiquement :
- `complet` : contenu ≥ 2000 caractères
- `partiel` : 500 à 1999 caractères
- `resume` : < 500 caractères

### 2.6 Nettoyage du texte (cleaner.py)

Le module `scrapers/cleaner.py` applique un pipeline de normalisation en 4 étapes :

1. **Normalisation Unicode** — `unicodedata.normalize("NFKD", texte)` : supprime les caractères de contrôle et normalise les espaces insécables, apostrophes courbes, etc.
2. **Décodage HTML** — suppression des entités HTML (`&amp;`, `&nbsp;`, etc.) via `html.unescape()`
3. **Suppression du bruit** — élimination par regex de : boutons de partage social (Facebook, Twitter, LinkedIn), mentions légales (copyright, CGU, politique cookies), appels à l'action (subscribe, download), liens relatifs de navigation, signatures de sources (AFP, Reuters)
4. **Nettoyage des espaces** — consolidation des espaces multiples et retours à la ligne excessifs

Un filtrage linguistique adapté est appliqué : les patterns FR et EN sont distincts.

Le contenu est rejeté (`return None`) si sa longueur après nettoyage est inférieure à 100 caractères (`LONGUEUR_MINIMALE`).

### 2.7 Parallélisation et performances

L'orchestrateur `scraper_all.py` lance les 22 scrapers en parallèle via `ThreadPoolExecutor` avec `MAX_WORKERS = 5` :

```python
with ThreadPoolExecutor(max_workers=5, thread_name_prefix="scraper") as executor:
    futures = {
        executor.submit(lancer_scraper, sid, date_depuis, mode_test): sid
        for sid in ids
    }
```

Chaque scraper est lancé comme **subprocess indépendant** (`subprocess.run()`), ce qui offre plusieurs avantages :
- **Isolation mémoire** : un crash d'un scraper n'affecte pas les autres
- **Pas de GIL** : vraie parallélisation (les subprocesses utilisent des processus distincts)
- **Timeout individuel** : chaque source a son propre timeout (600s par défaut, 900s pour DBA, Banque du Canada et CGAP)

Avec 5 workers, les 22 sources qui s'exécuteraient séquentiellement en ~90 minutes sont traitées en ~22 minutes (gain théorique de 4x, limité par les 2-3 sources les plus longues dans chaque batch).

---

## 3. Moteur RAG

### 3.1 Modèle d'embedding

| Paramètre | Valeur |
|-----------|--------|
| **Identifiant HuggingFace** | `intfloat/multilingual-e5-base` |
| **Dimensions du vecteur** | 384 |
| **Fenêtre de contexte** | 512 tokens |
| **Langues supportées** | 100+ langues (FR, EN, AR, PT…) |
| **Taille du modèle** | ~1,1 GB (poids + tokenizer) |
| **Bibliothèque** | sentence-transformers 5.4.1 |

Le modèle est chargé en **singleton lazy thread-safe** (double-checked locking) pour garantir qu'une seule instance existe en mémoire, même en cas d'appels concurrents depuis Streamlit :

```python
_model = None
_lock  = threading.Lock()

def get_model():
    global _model, _dim
    if _model is None:
        with _lock:
            if _model is None:
                m = SentenceTransformer(
                    EMBEDDING_MODEL,
                    cache_folder=os.environ.get("SENTENCE_TRANSFORMERS_HOME"),
                )
                _dim   = m.get_embedding_dimension()   # → 384
                _model = m
    return _model
```

**Préfixes e5 obligatoires**

Le modèle `multilingual-e5-base` requiert un préfixe textuel pour distinguer les types d'embeddings :

```python
prefix = "query: "   if is_query else "passage: "
prefixed = [prefix + t for t in textes]
embeddings = model.encode(prefixed, normalize_embeddings=True)
```

- `"query: "` → vecteur de requête (question utilisateur)
- `"passage: "` → vecteur de passage (chunk de document)

Les embeddings sont **normalisés L2** (`normalize_embeddings=True`), ce qui rend la similarité cosinus équivalente au produit scalaire et améliore la cohérence de la recherche.

### 3.2 Structure de la base vectorielle FAISS

L'index FAISS est persisté sur disque sous la forme de deux fichiers :

```
data/
├── faiss_index.bin       # Index sérialisé (faiss.write_index)
└── faiss_index_ids.npy   # Liste Python [chunk_id_0, chunk_id_1, ...] (numpy)
```

Le type d'index est sélectionné dynamiquement selon le volume de vecteurs :

| Volume | Type d'index | Caractéristiques |
|--------|-------------|-----------------|
| < 100 000 vecteurs | `IndexFlatL2` | Recherche exacte, O(n) |
| ≥ 100 000 vecteurs | `IndexIVFFlat` | Approximatif, nlist=256, scalable |

L'index est chargé en mémoire au premier appel (lazy loading) et reste en cache pour toute la durée de vie du processus.

**Indexation incrémentale**

Seuls les chunks dont `faiss_id IS NULL` en base sont indexés, en micro-batches de 256 :

```sql
SELECT id, contenu FROM chunks
WHERE faiss_id IS NULL
  AND contenu IS NOT NULL
  AND LENGTH(contenu) >= 50
LIMIT 256
```

Après indexation, le `faiss_id` est écrit en base (position dans l'index), permettant de retrouver le chunk SQLite depuis un résultat FAISS.

### 3.3 Découpage des articles (chunker.py)

| Paramètre | Valeur |
|-----------|--------|
| `CHUNK_SIZE` | 1600 caractères (~400 tokens) |
| `CHUNK_OVERLAP` | 200 caractères (~50 tokens) |
| `MIN_CHUNK_LEN` | 100 caractères |
| `BATCH_SIZE` | 100 articles par lot |

Le découpage est **récursif avec priorité de séparateurs** : `\n\n` > `\n` > `.` > `?` > `!` > découpe brute. Cette approche respecte la structure sémantique des textes (paragraphes > phrases > mots).

Un **filtrage thématique** est appliqué avant le découpage : les articles dont le contenu ne contient aucun des ~40 mots-clés d'inclusion financière sont marqués `qualite_contenu = 'hors_perimetre'` et exclus de l'indexation FAISS (mais conservés en base SQLite pour la recherche textuelle).

### 3.4 Recherche sémantique (retriever.py)

La fonction `rechercher()` exécute les étapes suivantes :

1. **Embedding de la requête** — `embed_query(query)` avec préfixe `"query: "`
2. **Recherche FAISS** — `index.search(query_vec, k_search)` avec `k_search = min(top_k * 8, index.ntotal)`
3. **Récupération SQLite** — jointure `chunks → articles → sources` pour les IDs retournés
4. **Filtres post-recherche** — filtre langue, filtre source_ids, filtre dimension
5. **Score de similarité** — normalisé : `score = 1 / (1 + distance_L2)`
6. **Résultats** — retourne jusqu'à `top_k` chunks avec métadonnées complètes

La surrecherche (`k_search = top_k * 8`) compense les pertes dues aux filtres post-recherche, garantissant un nombre suffisant de résultats pertinents même avec des filtres actifs.

### 3.5 Données mesurées en production

| Indicateur | Valeur observée |
|------------|----------------|
| Articles collectés | 2 630 |
| Sources actives | 28 |
| Taille de l'index FAISS | 13,3 MB |
| Temps de chargement du modèle e5 | ~8 secondes (premier appel) |
| Latence recherche FAISS (IndexFlatL2) | < 50 ms |
| Scores de similarité typiques | 0,35 – 0,75 (questions métier) |

---

## 4. Agent pydantic-ai

### 4.1 Architecture de l'agent

L'agent SVIA est construit avec **pydantic-ai 1.105.0**, un framework d'orchestration d'agents LLM qui garantit des sorties structurées (Pydantic BaseModel). Deux instances d'agent coexistent :

- `svia_agent` — exécution synchrone pour les tool calls (Phase 1)
- `svia_stream_agent` — exécution streaming token-by-token (Phase 2)

**Modèle de sortie structurée :**

```python
class SVIAResponse(BaseModel):
    reponse: str          # Synthèse factuelle 300-400 mots, sourcée
    suggestions: list[SuggestionItem]  # 2-3 recommandations actionnables CEMAC/SRIF
    dimension: str | None # Dimension IF principale détectée
    requete_rag: str      # Requête enrichie utilisée pour la recherche
```

### 4.2 Prompt système

Le prompt système (`_SYSTEM_SVIA`) définit quatre règles comportementales :

- **RÈGLE 1 — Salutations** : réponse directe courte, aucun tool call
- **RÈGLE 2 — Questions métier** : appel obligatoire à `search_corpus` en premier, synthèse structurée 300-400 mots avec citations sources
- **RÈGLE 3 — Qualité** : réponse fondée uniquement sur les documents trouvés ; mention explicite si l'information est absente du corpus
- **RÈGLE 4 — Confidentialité/Identité** : ne jamais décrire l'architecture technique interne ; réponse identitaire standard si demandée

Le prompt ancre l'agent sur les 6 dimensions IF de la BEAC (Accès, Utilisation, Qualité, Éducation financière, Protection des consommateurs, Innovation financière) et les 6 pays CEMAC.

### 4.3 Les 5 outils de l'agent

**Outil 1 : `search_corpus`**

Recherche sémantique dans le corpus. Enrichit automatiquement la requête avec les filtres zone et cible sélectionnés par l'utilisateur. Applique un reranking par longueur de contenu (bonus +10% pour chunks > 800 chars, malus -30% pour chunks < 200 chars). Déduplique les résultats par article pour éviter plusieurs chunks du même article dans le contexte. Collecte les métadonnées sources pour affichage dans l'UI.

**Outil 2 : `classify_dimension`**

Classifie le texte parmi les 6 dimensions IF par correspondance de mots-clés normalisés (sans diacritiques, insensible à la casse). Chaque dimension dispose d'une liste de mots-clés spécifiques. La dimension avec le score le plus élevé est retenue. Informe l'agent pour orienter la synthèse et les suggestions.

**Outil 3 : `generate_suggestions`**

Interroge la table `historique_actions_diif` pour récupérer les actions DIIF récentes filtrées par dimension détectée. Retourne ces contextes au LLM pour qu'il génère des recommandations complémentaires et non redondantes avec l'existant.

**Outil 4 : `get_recent_articles`** *(outil auxiliaire)*

Retourne les articles récents de la base (7 derniers jours par défaut) pour alimenter des questions de type "quoi de neuf" sans nécessiter de recherche sémantique.

**Outil 5 : `get_source_stats`** *(outil auxiliaire)*

Retourne les statistiques de couverture par source (nombre d'articles, dernière mise à jour) pour répondre aux questions sur la couverture du système.

### 4.4 Logique de sélection des outils

L'agent sélectionne les outils de façon autonome selon le contenu de la question. Le comportement agentique observé :

1. **Salutation pure** → Aucun outil. Réponse directe.
2. **Question thématique** → `search_corpus` (obligatoire) → `classify_dimension` → `generate_suggestions`
3. **Question sur la couverture** → `get_source_stats` ou `get_recent_articles`
4. **Question avec contexte multi-sources** → `search_corpus` (top_k augmenté) → `classify_dimension`

La commande `/sources` dans le chatbot contourne l'agent et affiche directement la liste des sources depuis la base.

### 4.5 Mode streaming (2 phases)

Le streaming est implémenté en deux phases pour permettre aux tool calls (synchrones) de s'exécuter complètement avant de démarrer le streaming de la réponse textuelle :

**Phase 1 — Tool calls (synchrone)**

```python
result = loop.run_until_complete(
    svia_agent.run(question, deps=deps, message_history=historique)
)
# → SVIAResponse avec contexte RAG collecté dans deps
```

**Phase 2 — Streaming token-by-token (asynchrone)**

```python
async def _run():
    async with svia_stream_agent.run_stream(prompt) as stream_result:
        async for token in stream_result.stream_text(delta=True):
            q.put(token)  # queue thread-safe

# Thread daemon → loop asyncio dédiée → yield tokens
```

Le passage d'informations entre les deux phases se fait via l'objet `SVIADeps` : le contexte RAG formaté (`contexte_formate`) collecté en Phase 1 est injecté comme document de référence dans le prompt de Phase 2.

### 4.6 Guardrails — 4 couches de sécurité

**Couche 1 — Détection de prompt injection**

Vérifie la présence de 15+ patterns regex associés aux techniques de jailbreak : instructions d'oubli (`ignore previous instructions`, `oublie tes instructions`), redéfinition d'identité (`tu es maintenant`, `act as`), mode développeur (`DAN`, `developer mode`), balises système (`<system>`, `[INST]`, `### system`).

**Couche 2 — Détection de tentative d'accès confidentiel**

Filtre les questions cherchant à extraire : mots de passe, clés API, schéma de base de données, prompts système, architecture interne (FAISS, embeddings). Protège contre l'exfiltration d'informations sensibles via le LLM.

**Couche 3 — Hors périmètre**

Rejette les questions sans rapport avec l'inclusion financière/CEMAC si elles contiennent des signaux négatifs (sport, cuisine, météo, séries TV, etc.) ET aucun ancrage financier. La logique est intentionnellement permissive : une question ambiguë passe plutôt qu'une question légitime ne soit bloquée.

**Couche 4 — Validation de sortie**

Appliquée après génération de la réponse :
- Vérification longueur minimale (> 50 chars, sauf salutations)
- Masquage automatique de secrets (`[REDACTED]`) via regex sur clés API et tokens
- Détection et censure de fragments du prompt système qui auraient fuité dans la réponse
- Nettoyage retourné dans `GuardrailResult.reponse_nettoyee`

### 4.7 Paramètres LLM

| Paramètre | Valeur |
|-----------|--------|
| **Modèle smart** | `claude-sonnet-4-5` (pydantic-ai agent) |
| **Modèle fast** | `claude-haiku-4-5-20251001` (résumés rapides) |
| **Modèle synthèse éditoriale** | `claude-sonnet-4-5` (via SDK anthropic direct) |
| **max_tokens synthèse** | 1500 |
| **Température** | Non configurée (défaut pydantic-ai) |
| **Fournisseur alternatif** | OpenAI (`gpt-4o` / `gpt-4o-mini`) via `LLM_PROVIDER=openai` |

---

## 5. Interface Streamlit

### 5.1 Architecture SPA

L'application est une **Single Page Application** gérée par `app.py` (516 lignes). Le routage est assuré par `st.session_state["page"]` :

```python
PAGE_MAP = {
    "dashboard":             render_dashboard,
    "veille":                render_veille,
    "chatbot":               render_chatbot,
    "export":                render_export,
    "admin":                 render_admin,
    "gestion_sources":       render_gestion_sources,
    "gestion_utilisateurs":  render_gestion_utilisateurs,
    "logs":                  render_logs,
    "nuage":                 render_nuage,
    "suggestions":           render_suggestions,
}
```

### 5.2 Système d'authentification

- **Algorithme** : JWT (HS256) avec expiration 8 heures
- **Hashage** : bcrypt (salt automatique, work factor par défaut)
- **Rôles** : `administrateur` / `lecteur`
- **Réinitialisation mdp** : token UUID → email HTML SMTP → lien temporaire → validation + nouveaux critères (8 chars min, 1 majuscule, 1 chiffre)
- **Audit** : chaque connexion (succès/échec) est enregistrée dans `logs_activite`

La page de login est rendue en plein écran avec animations CSS (particules flottantes, carte avec effet `border-glow` et `fade-in`).

### 5.3 Pages et fonctionnalités

**Dashboard** (`ui/pages/dashboard.py` — 273 lignes)

- 4 métriques principales : articles totaux, documents, sources actives, dernière collecte
- Graphique d'évolution temporelle mensuelle (Plotly bar chart)
- Répartition par source (bar chart horizontal) et par langue (pie chart)
- Couverture par dimension IF (6 jauges avec compteurs)
- Fil des 10 dernières publications
- Caching Streamlit : TTL 300s pour les statistiques lourdes, 60s pour les articles récents

**Veille** (`ui/pages/veille.py` — 481 lignes) — 4 onglets

- *Articles collectés* : filtres cumulables (Dimension IF, Cible CEMAC, Zone géographique, Langue, Qualité contenu, Date, Mot-clé) ; pagination 20 articles/page ; expanders avec contenu complet et lien source
- *Qualité du scraping* : statistiques complet/partiel/résumé par source, alertes si < 30% de contenu complet
- *Documents* : upload PDF/DOCX/TXT, extraction texte automatique, liste avec suppression (admins)
- *Collecte* (admins) : sélection date début, lancement manuel avec rapport temps réel, démarrage/arrêt du planificateur automatique

**Chatbot** (`ui/pages/chatbot.py` — 342 lignes)

- Filtres sidebar : Dimension IF, Zone CEMAC, Cible démographique, top_k (2-15)
- Historique de conversation persisté en `st.session_state`
- Affichage sources citées dans expander après chaque réponse
- Recommandations DIIF dans expander distinct
- Commande spéciale `/sources` : liste les sources actives sans appel LLM
- Streaming token-by-token via `st.write_stream()`

**Export** (`ui/pages/export.py` — 282 lignes)

- *Génération rapport* : sélection période (7/14/30/60/90 jours), option recommandations, aperçu articles/sources/période, téléchargement Word et PDF
- *Envoi email* : destinataires automatiques (admins) + adresses supplémentaires, sélection période, envoi immédiat, configuration bulletin automatique hebdomadaire (jour + heure)

### 5.4 Filtres de consultation implémentés

| Filtre | Type | Valeurs possibles |
|--------|------|-------------------|
| Dimension IF | Selectbox | Accès / Utilisation / Qualité / Éducation financière / Protection des consommateurs / Innovation financière |
| Zone géographique | Selectbox | Cameroun / Congo / Gabon / Guinée Équatoriale / RCA / Tchad / Zone CEMAC / Afrique / Monde |
| Cible démographique | Selectbox | Femmes +25 ans / Jeunes 15-24 ans / Populations rurales / MPME |
| Langue | Selectbox | Français / Anglais |
| Qualité contenu | Multiselect | complet / partiel / résumé |
| Période | Date picker | Sélection plage date publication ou collecte |
| Mot-clé | Text input | Recherche textuelle dans titre + contenu |
| Source | Multiselect | Toutes les sources actives |
| top_k RAG | Slider | 2 à 15 chunks |

### 5.5 Identité visuelle BEAC

L'application utilise une palette institutionnelle injectée via CSS Streamlit (`st.markdown(unsafe_allow_html=True)`) :

| Élément | Couleur |
|---------|---------|
| Navy principal | `#002B5C` |
| Or accent | `#C8A951` |
| Fond sidebar | Gradient `#001d3d → #002B5C` |
| Messages assistant | Beige `#FDF8EC` |
| Messages utilisateur | Bleu clair |
| Bordures actives | `#C8A951` |

### 5.6 Module d'export et d'envoi email

**Rapport Word (.docx)**

Généré via `python-docx` avec mise en forme institutionnelle : page de garde (logo, titre, période), section synthèse éditoriale (générée par Claude), actualités classées par dimension IF, liste des sources consultées, recommandations DIIF optionnelles, pied de page.

**Rapport PDF**

Généré via ReportLab avec la même structure. Les deux formats sont disponibles en téléchargement direct depuis l'interface.

**Envoi email SMTP**

- Corps email : HTML avec synthèse + aperçu articles
- Pièce jointe : rapport Word (.docx)
- Protocole : SMTP + STARTTLS (port 587, configurable)
- Destinataires : admins actifs en base + adresses supplémentaires
- Protection : limite 3 demandes de reset/heure, logs systématiques

---

## 6. Déploiement Docker

### 6.1 Dockerfile

```dockerfile
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    HF_HOME=/app/models \
    HUGGINGFACE_HUB_CACHE=/app/models/hub \
    TRANSFORMERS_CACHE=/app/models/hub \
    SENTENCE_TRANSFORMERS_HOME=/app/models/hub

WORKDIR /app

RUN apt-get update && apt-get install -y curl \
    && rm -rf /var/lib/apt/lists/*

# Wheel torch Linux CPU — évite 700 MB de téléchargement
COPY local_packages/wheels/torch*.whl /tmp/
RUN pip install --no-cache-dir /tmp/torch*.whl && rm /tmp/torch*.whl

# Autres dépendances (torch exclu pour éviter doublon)
COPY requirements.txt .
RUN grep -vE "^torch" requirements.txt > /tmp/req_light.txt \
    && pip install --no-cache-dir -r /tmp/req_light.txt \
    && rm /tmp/req_light.txt

# Modèle HuggingFace embarqué (pas de téléchargement au runtime)
COPY model_cache/models--intfloat--multilingual-e5-base \
     /app/models/hub/models--intfloat--multilingual-e5-base

# Code source
COPY . .

RUN mkdir -p data/uploads data/exports data/backups

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s \
    CMD curl -f http://localhost:8501/_stcore/health || exit 1

CMD ["python", "-m", "streamlit", "run", "app.py", \
     "--server.port=8501", "--server.address=0.0.0.0", \
     "--server.headless=true"]
```

**Choix de conception — autonomie totale**

L'image est conçue pour fonctionner **sans accès Internet** lors du build et du runtime :

| Composant | Stratégie |
|-----------|-----------|
| PyTorch 2.6.0+cpu | Wheel Linux téléchargé une fois, copié dans `local_packages/wheels/` |
| Modèle multilingual-e5-base | Copié depuis le cache HuggingFace local dans `model_cache/` |
| Toutes les autres dépendances | Installées depuis PyPI au build uniquement |

### 6.2 docker-compose.yml

```yaml
services:
  svia:
    image: svia-diif-beac:test
    container_name: svia_app
    env_file:
      - .env
    ports:
      - "8501:8501"
    volumes:
      - ./data:/app/data
    restart: unless-stopped
```

### 6.3 Taille et volumes

| Élément | Taille |
|---------|--------|
| **Image Docker totale** | 2,82 GB |
| — python:3.11-slim (base) | ~130 MB |
| — PyTorch 2.6.0+cpu | ~700 MB |
| — sentence-transformers + dépendances | ~500 MB |
| — Modèle multilingual-e5-base | ~1,1 GB |
| — Code applicatif | ~5 MB |
| **Volume data/ (hôte)** | Variable |
| — veille_diif.db (2630 articles) | ~45 MB |
| — faiss_index.bin | 13,3 MB |
| — faiss_index_ids.npy | <1 MB |

### 6.4 Commandes de démarrage et d'arrêt

```bash
# Démarrage (depuis le répertoire du projet)
docker compose up -d

# Vérification de l'état
docker compose ps

# Consultation des logs
docker compose logs --tail=50 svia

# Arrêt propre
docker compose down

# Rebuild complet de l'image
docker build -t svia-diif-beac:test .

# Lancement sans compose (debug)
docker run -p 8501:8501 --env-file .env \
  -v "$(pwd)/data:/app/data" \
  svia-diif-beac:test
```

### 6.5 Variables d'environnement (.env)

| Variable | Description | Requis |
|----------|-------------|--------|
| `ANTHROPIC_API_KEY` | Clé API Anthropic | Oui |
| `APP_SECRET_KEY` | Clé de signature JWT | Oui |
| `DB_PATH` | Chemin base SQLite | Non (défaut: `data/veille_diif.db`) |
| `LLM_PROVIDER` | `anthropic` ou `openai` | Non (défaut: `anthropic`) |
| `SMTP_HOST` | Serveur email | Non (requis pour email) |
| `SMTP_USER` | Compte email | Non |
| `SMTP_PASSWORD` | Mot de passe SMTP | Non |
| `SCRAPING_INTERVAL_HOURS` | Intervalle collecte auto | Non (défaut: 168 = 7j) |
| `EMBEDDING_MODEL` | Modèle HuggingFace | Non (défaut: `intfloat/multilingual-e5-base`) |

---

## 7. Tests et CI/CD

### 7.1 GitHub Actions — Workflow CI

**Fichier :** `.github/workflows/ci.yml`

Le workflow CI est déclenché sur chaque `push` vers `main` ou `develop`, et sur chaque Pull Request vers `main`. Il exécute deux jobs séquentiels :

**Job 1 : Lint (flake8)**

```yaml
- run: pip install flake8
- run: |
    flake8 agents/svia_agent.py core/guardrails.py core/schemas.py tests/ \
      --max-line-length=120 \
      --ignore=E501,W503,E241
```

Vérifie la syntaxe et le style des modules critiques (agent, guardrails, schémas).

**Job 2 : Tests pytest** (conditionné au succès du lint)

```yaml
env:
  ANTHROPIC_API_KEY: sk-ant-test-key-for-ci
  LLM_PROVIDER: anthropic
  DB_PATH: ":memory:"      # Base SQLite in-memory pour isolation totale

- run: pip install -r requirements.txt pytest pytest-asyncio
- run: pytest tests/ -v --tb=short
```

L'utilisation de `DB_PATH=":memory:"` garantit l'isolation complète des tests : chaque exécution repart d'une base vide, sans dépendance à des données persistées.

### 7.2 GitHub Actions — Workflow Docker

**Fichier :** `.github/workflows/docker.yml`

Déclenché sur chaque push vers `main`. Build l'image Docker et la publie sur GitHub Container Registry (GHCR) :

```yaml
- uses: docker/login-action@v3
  with:
    registry: ghcr.io
    username: ${{ github.actor }}
    password: ${{ secrets.GITHUB_TOKEN }}

- uses: docker/build-push-action@v5
  with:
    context: .
    push: true
    tags: ghcr.io/${{ github.repository }}:${{ github.sha }}
```

L'image est taguée avec le SHA du commit (`github.sha`), garantissant la traçabilité entre le code source et l'artefact Docker déployé.

### 7.3 Structure des tests

Les tests pytest sont localisés dans `tests/` (exclu du dépôt git via `.gitignore` pour des raisons de confidentialité). Ils couvrent :

- **Tests unitaires des guardrails** : vérification que les 4 couches bloquent les inputs malveillants et laissent passer les inputs légitimes
- **Tests unitaires du chunker** : vérification du découpage récursif, des overlaps, du filtrage thématique
- **Tests du cleaner** : normalisation Unicode, suppression du bruit, cas limites (texte vide, texte trop court)
- **Tests d'intégration RAG** : pipeline chunking → indexation → retrieval sur une base SQLite in-memory
- **Tests de l'authentification** : bcrypt, JWT création/validation/expiration, force du mot de passe
- **Tests des schémas Pydantic** : validation des modèles d'entrée/sortie de l'agent

---

## Annexe A — Diagramme de séquence — Requête utilisateur complète

```
Utilisateur      Streamlit UI      Guardrails     SVIA Agent       FAISS        Claude API
    │                 │                │               │              │              │
    │── question ────►│                │               │              │              │
    │                 │── verifier ───►│               │              │              │
    │                 │                │◄── ok ────────│              │              │
    │                 │                │               │              │              │
    │                 │── orchestrer ──────────────────►              │              │
    │                 │                │               │              │              │
    │                 │                │               │── search ───►│              │
    │                 │                │               │◄── chunks ───│              │
    │                 │                │               │              │              │
    │                 │                │               │── classify_dimension        │
    │                 │                │               │── generate_suggestions      │
    │                 │                │               │              │              │
    │                 │                │               │── run_stream ──────────────►│
    │                 │                │               │              │              │
    │                 │◄── tokens (stream) ────────────────────────────────────────│
    │◄── affichage ───│                │               │              │              │
    │    progressif   │                │               │              │              │
    │                 │── verifier_sortie ────────────►│              │              │
    │                 │                │◄── ok ────────│              │              │
    │                 │                │               │              │              │
    │◄── sources + suggestions ────────│               │              │              │
```

---

## Annexe B — Schéma de la base de données SQLite

```sql
utilisateurs (id, nom, email, mot_de_passe_hash, role, actif, cree_le, derniere_connexion)
sources      (id, nom, url, type_source, langue, active, frequence_heures, cree_le)
articles     (id, source_id→sources, titre, contenu, resume, url_original UNIQUE,
              publie_le, collecte_le, langue, qualite_contenu, est_doublon, indexe)
chunks       (id, article_id→articles, contenu, position, faiss_id, indexe_le)
documents    (id, nom_fichier, chemin_stockage, type_doc, description,
              uploade_par, uploade_le, indexe)
notifications      (id, utilisateur_id→utilisateurs, message, dimension, lue, cree_le)
logs_activite      (id, utilisateur_id→utilisateurs, action, entite_type, entite_id,
                    detail, ip, cree_le)
historique_actions_diif (id, description, dimension, zone, cible, date_action)
reset_tokens       (id, utilisateur_id→utilisateurs, token UNIQUE, expire_le, utilise)
parametres         (cle PRIMARY KEY, valeur, mis_a_jour_le)
```

---

*Document généré le 2026-06-11 — Projet SVIA DIIF/BEAC — Version 1.0*
