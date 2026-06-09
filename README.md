# Système de Veille Informationnelle Automatisée (SVIA)

![CI](https://github.com/Vanelle-Ayonta/veille-diif-beac/actions/workflows/ci.yml/badge.svg)

---

## Stack technique

| Composant | Technologie |
|---|---|
| Interface | Streamlit 1.45 |
| Base de données | SQLite (veille_diif.db) |
| LLM | Anthropic Claude (Sonnet + Haiku) |
| Embeddings | intfloat/multilingual-e5-base |
| Index vectoriel | FAISS (IndexFlatL2 → IVFFlat) |
| Authentification | JWT + bcrypt |
| Export | python-docx + ReportLab |
| Scraping | requests + BeautifulSoup + feedparser |

---

## Installation locale

### Prérequis
- Python 3.10+
- pip

### Étapes

```bash
# 1. Cloner le dépôt
git clone https://github.com/VOTRE_USERNAME/veille-diif-beac.git
cd veille-diif-beac

# 2. Créer et activer l'environnement virtuel
python -m venv env_rag
# Windows
env_rag\Scripts\activate
# Linux/Mac
source env_rag/bin/activate

# 3. Installer les dépendances
pip install -r requirements.txt

# 4. Configurer les variables d'environnement
cp .env.example .env
# Éditer .env avec vos clés API

# 5. Initialiser la base de données
python init_db.py

# 6. Lancer la collecte initiale
python scrapers/scraper_all.py --depuis 2023-01-01

# 7. Indexer le corpus
python core/rag/run_pipeline.py

# 8. Lancer l'application
python -m streamlit run app.py
```

---

## Configuration

Copier `.env.example` en `.env` et renseigner :

```env
ANTHROPIC_API_KEY=sk-ant-api03-...
APP_SECRET_KEY=votre_secret
SMTP_USER=votre@gmail.com
SMTP_PASSWORD=mot_de_passe_application
APP_URL=http://localhost:8501
```

---

## Identifiants par défaut

| Champ | Valeur |
|---|---|
| Email | admin@beac.int |
| Mot de passe | Admin@DIIF2025 |

> ⚠️ Changer le mot de passe dès la première connexion.

---

## Commandes utiles

```bash
# Collecte manuelle
python scrapers/scraper_all.py --depuis 2024-01-01

# Sources internationales uniquement
python scrapers/scraper_intl.py --source all --depuis 2024-01-01

# Pipeline RAG incrémental
python core/rag/run_pipeline.py

# Reconstruire l'index depuis zéro
python core/rag/run_pipeline.py --rebuild

# Statistiques
python scrapers/scraper_all.py --stats
python core/rag/run_pipeline.py --stats

# Test recherche sémantique
python core/rag/run_pipeline.py --test "inclusion financière femmes CEMAC"
```

---

## Déploiement Streamlit Cloud

1. Pousser le dépôt sur GitHub (privé)
2. Connecter sur [share.streamlit.io](https://share.streamlit.io)
3. Configurer les secrets dans Advanced Settings
4. Fichier principal : `app.py`

Variables à configurer dans Streamlit Cloud Secrets :
```toml
ANTHROPIC_API_KEY = "..."
APP_SECRET_KEY = "..."
SMTP_USER = "..."
SMTP_PASSWORD = "..."
APP_URL = "https://votre-app.streamlit.app"
```

---

## Sources couvertes

### Groupe 1 — Médias spécialisés Afrique/IF
- Digital Business Africa (FR)
- FinDev Gateway (EN)
- AFI Global (EN)
- La Finance pour Tous (FR)

### Groupe 2 — Organisations internationales
- GSMA (EN)
- BRI/BIS (EN)
- Banque de France (FR)

### Groupe 3 — Institutions régionales CEMAC
- CNEF Cameroun (FR)
- GIMAC (FR)
- BCEAO (FR)
- Bank Al-Maghrib (FR)

### Groupe 4 — Banques centrales africaines
- Central Bank of Kenya (EN)
- CBN Nigeria (EN)
- BNR Rwanda (EN)
- Banque du Canada (EN)

### Groupe 5 — Sources internationales IF
- Banque mondiale (EN)
- CGAP (EN)
- Women's World Banking (EN)
- Better Than Cash Alliance (EN)
- Center for Financial Inclusion (EN)
- ADA Luxembourg (FR)
- AFD (FR)

---

## Dimensions d'inclusion financière

| Dimension | Description |
|---|---|
| Accès | Disponibilité des services financiers |
| Utilisation | Usage effectif des services |
| Qualité | Adéquation aux besoins |
| Éducation financière | Compétences et sensibilisation |
| Protection des consommateurs | Droits et recours |
| Innovation financière | Fintech, CBDC, digital |

---

## Auteur

Développé dans le cadre d'un mémoire professionnel ISE3
à l'ISSEA (Yaoundé, Cameroun).

Stagiaire : DIIF — Département de l'Inclusion et de
l'Innovation Financières, BEAC.

---

*Document confidentiel — Usage interne DIIF/BEAC*