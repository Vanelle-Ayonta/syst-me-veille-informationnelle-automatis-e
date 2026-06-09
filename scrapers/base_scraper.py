"""
scrapers/base_scraper.py — Module commun partagé par tous les scrapers
=======================================================================
Fournit :
  - Connexion à veille_diif.db (base unique)
  - get_or_create_source() — enregistre la source si absente
  - url_existe()           — déduplication globale
  - sauvegarder_article()  — insertion + nettoyage à la volée
  - evaluer_qualite()      — complet / partiel / resume / inconnu
  - now_iso()              — horodatage UTC
"""
import os
import sys
import uuid
import sqlite3
from datetime import datetime
from contextlib import contextmanager

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJECT_ROOT)
from config import DB_PATH as _DB_PATH_CONFIG

# Résolution en chemin absolu indépendant du cwd courant du sous-processus
DB_PATH = (
    _DB_PATH_CONFIG
    if os.path.isabs(_DB_PATH_CONFIG)
    else os.path.join(_PROJECT_ROOT, _DB_PATH_CONFIG)
)

# Import du pipeline de nettoyage
try:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from cleaner import nettoyer
    CLEANER_OK = True
except ImportError:
    CLEANER_OK = False
    def nettoyer(texte, titre="", langue="fr"):
        return texte if texte and len(texte) >= 100 else None


# ── Détection du filtre date depuis argv (défini une seule fois) ──────────
_ARGV_DATE_FILTRE: str | None = None
_ARGV_DATE_PARSED: bool = False


def _get_argv_date() -> str | None:
    """Lit --depuis YYYY-MM-DD dans sys.argv du sous-processus scraper."""
    global _ARGV_DATE_FILTRE, _ARGV_DATE_PARSED
    if not _ARGV_DATE_PARSED:
        _ARGV_DATE_PARSED = True
        if "--depuis" in sys.argv:
            idx = sys.argv.index("--depuis")
            if idx + 1 < len(sys.argv):
                _ARGV_DATE_FILTRE = sys.argv[idx + 1]
    return _ARGV_DATE_FILTRE


def now_iso() -> str:
    return datetime.utcnow().isoformat()

def new_id() -> str:
    return str(uuid.uuid4())

def evaluer_qualite(contenu: str) -> str:
    if not contenu:
        return "inconnu"
    n = len(contenu.strip())
    if n >= 2000: return "complet"
    if n >= 500:  return "partiel"
    return "resume"


@contextmanager
def get_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_or_create_source(nom: str, url: str = "", langue: str = "fr",
                          type_source: str = "web") -> str:
    """Retourne le source_id existant ou crée la source dans veille_diif.db."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT id FROM sources WHERE nom = ?", (nom,)
        ).fetchone()
        if row:
            return row["id"]
        sid = new_id()
        conn.execute("""
            INSERT INTO sources
                (id, nom, url, type_source, langue, active, frequence_heures, cree_le)
            VALUES (?, ?, ?, ?, ?, 1, 168, ?)
        """, (sid, nom, url, type_source, langue, now_iso()))
        return sid


def url_existe(url: str) -> bool:
    """True si l'URL est déjà dans veille_diif.db."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT id FROM articles WHERE url_original = ?", (url,)
        ).fetchone()
        return row is not None


def sauvegarder_article(source_id: str, article: dict,
                        date_debut_filtre: str = None) -> bool:
    """
    Insère un article dans veille_diif.db après nettoyage du contenu.
    Retourne True si insertion réussie, False si doublon ou article trop ancien.

    Champs attendus dans article (noms des scrapers originaux) :
        url / url_original
        titre
        contenu
        resume
        date_publication / publie_le
        langue
        date_scraping / collecte_le   (optionnel)

    date_debut_filtre : filtre de date explicite (YYYY-MM-DD).
        Si None, la date est auto-détectée depuis --depuis dans sys.argv.
        Un article dont publie_le < date_debut_filtre est rejeté (return False).
    """
    url = article.get("url") or article.get("url_original") or ""
    if not url or url_existe(url):
        return False

    # ── Filtre date de publication (filet de sécurité) ────────────────────
    filtre_actif = date_debut_filtre or _get_argv_date()
    publie_le_raw = (
        article.get("date_publication") or
        article.get("publie_le") or ""
    )
    if filtre_actif and publie_le_raw:
        try:
            date_pub = datetime.strptime(str(publie_le_raw)[:10], "%Y-%m-%d").date()
            date_limite = datetime.strptime(filtre_actif, "%Y-%m-%d").date()
            if date_pub < date_limite:
                import logging as _log
                _log.getLogger(__name__).debug(
                    f"[SKIP] Trop ancien : {publie_le_raw[:10]} < {filtre_actif}"
                )
                return False
        except Exception:
            pass  # date non parseable → on collecte quand même

    titre   = str(article.get("titre") or "")[:500]
    langue  = str(article.get("langue") or "fr")[:5]
    resume  = str(article.get("resume") or "")[:1000]
    contenu_brut = str(article.get("contenu") or "")

    # Nettoyage du contenu via cleaner.py
    contenu_propre = nettoyer(contenu_brut, titre=titre, langue=langue)
    if contenu_propre is None:
        contenu_propre = contenu_brut[:6000]  # fallback sans nettoyage

    qualite = evaluer_qualite(contenu_propre)

    publie_le = (
        article.get("date_publication") or
        article.get("publie_le") or ""
    )
    collecte_le = (
        article.get("date_scraping") or
        article.get("collecte_le") or
        now_iso()
    )

    with get_db() as conn:
        conn.execute("""
            INSERT OR IGNORE INTO articles (
                id, source_id, titre, contenu, resume,
                url_original, publie_le, collecte_le,
                langue, est_doublon, indexe, qualite_contenu
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?)
        """, (
            new_id(), source_id,
            titre,
            contenu_propre[:6000],
            resume,
            url,
            str(publie_le) if publie_le else None,
            str(collecte_le),
            langue,
            qualite,
        ))
    return True
