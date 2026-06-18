import os
from dotenv import load_dotenv
load_dotenv()

# Sur HuggingFace Spaces, /data est un disque persistant monté automatiquement.
# En local ou Docker standard, on utilise le dossier data/ relatif au projet.
_HF_SPACE  = os.getenv("HF_SPACE", "false").lower() == "true"
_DATA_ROOT = "/data" if _HF_SPACE else "data"

APP_NAME   = os.getenv("APP_NAME", "Veille DIIF/BEAC")
SECRET_KEY = os.getenv("APP_SECRET_KEY", "dev_secret_key_insecure")
DB_PATH    = os.getenv("DB_PATH", f"{_DATA_ROOT}/veille_diif.db")

LLM_PROVIDER          = os.getenv("LLM_PROVIDER", "anthropic")

ANTHROPIC_API_KEY     = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL_SMART = os.getenv("ANTHROPIC_MODEL_SMART", "claude-sonnet-4-5")
ANTHROPIC_MODEL_FAST  = os.getenv("ANTHROPIC_MODEL_FAST", "claude-haiku-4-5-20251001")

OPENAI_API_KEY        = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL_SMART    = os.getenv("OPENAI_MODEL_SMART", "gpt-4o")
OPENAI_MODEL_FAST     = os.getenv("OPENAI_MODEL_FAST", "gpt-4o-mini")

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "intfloat/multilingual-e5-base")

# ── Reranker cross-encoder (étape 2b) ────────────────────────────────────────
# Modèle multilingue FR/EN léger (~135 MB), entraîné sur MS MARCO multilingue.
# Mettre USE_RERANKER=false dans .env pour désactiver (ex: machine sans RAM).
RERANKER_MODEL = os.getenv(
    "RERANKER_MODEL",
    "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
)
USE_RERANKER = os.getenv("USE_RERANKER", "true").lower() == "true"

SMTP_HOST     = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT     = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER     = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
MAIL_FROM     = os.getenv("MAIL_FROM", "Veille DIIF/BEAC")
APP_URL       = os.getenv("APP_URL", "http://localhost:8501")

SCRAPING_INTERVAL_HOURS = int(os.getenv("SCRAPING_INTERVAL_HOURS", "168"))

UPLOADS_DIR      = os.getenv("UPLOADS_DIR",      f"{_DATA_ROOT}/uploads")
EXPORTS_DIR      = os.getenv("EXPORTS_DIR",      f"{_DATA_ROOT}/exports")
BACKUPS_DIR      = os.getenv("BACKUPS_DIR",      f"{_DATA_ROOT}/backups")
FAISS_INDEX_PATH = os.getenv("FAISS_INDEX_PATH", f"{_DATA_ROOT}/faiss_index")

DIMENSIONS_IF = [
    "Accès",
    "Utilisation",
    "Qualité",
    "Éducation financière",
    "Protection des consommateurs",
    "Innovation financière",
]
CIBLES_IF = [
    "Femmes +25 ans",
    "Jeunes 15-24 ans",
    "Populations rurales",
    "MPME",
]
ZONES_CEMAC = [
    "Cameroun", "Congo", "Gabon", "Guinée Équatoriale",
    "RCA", "Tchad", "Zone CEMAC", "Afrique", "Monde",
]

ROLE_ADMIN   = "administrateur"
ROLE_LECTEUR = "lecteur"
ROLES        = [ROLE_ADMIN, ROLE_LECTEUR]

JWT_ALGORITHM    = "HS256"
JWT_EXPIRY_HOURS = 8

def get_model(task: str = "smart") -> str:
    """Retourne le nom du modèle selon LLM_PROVIDER et la tâche demandée."""
    if LLM_PROVIDER == "openai":
        return OPENAI_MODEL_SMART if task == "smart" else OPENAI_MODEL_FAST
    return ANTHROPIC_MODEL_SMART if task == "smart" else ANTHROPIC_MODEL_FAST
