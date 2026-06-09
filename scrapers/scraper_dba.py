"""
Scraper — Digital Business Africa (v2)
=======================================
Collecte les articles et les stocke dans une base SQLite.
Chaque article est horodaté pour permettre un filtrage par date.

STRATÉGIE D'ACCÈS
─────────────────
Digital Business Africa est un site WordPress. Le scraper tente
les méthodes suivantes dans l'ordre :

  1. Flux RSS  : /feed/ et /en/feed/ paginés
     → Source officielle, données structurées (titre, date, résumé, URL)

  2. Sitemap XML : /wp-sitemap-posts-post-1.xml, -2.xml ...
     → Liste exhaustive de toutes les URLs d'articles

NOTE RÉSEAU : Si le script retourne des erreurs 403, c'est un filtrage
réseau côté serveur. Exécuter le script depuis un poste avec accès
internet direct (ex: poste de travail au DIIF, pas depuis un serveur).

USAGE
─────
    python scraper_dba.py                      # collecte complète (RSS + sitemap)
    python scraper_dba.py --depuis 2024-01-01  # articles depuis une date
    python scraper_dba.py --methode rss        # RSS uniquement
    python scraper_dba.py --methode sitemap    # sitemap uniquement
    python scraper_dba.py --test               # 1 page RSS (validation rapide)
    python scraper_dba.py --stats              # statistiques de la base

FILTRER PAR DATE (après collecte, dans un autre script)
───────────────────────────────────────────────────────
    from scraper_dba import requete_par_date
    articles = requete_par_date(date_debut='2025-01-01', langue='fr')
"""

import requests
from bs4 import BeautifulSoup
import sqlite3
import time
import argparse
import logging
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from base_scraper import get_or_create_source, url_existe, sauvegarder_article
SOURCE_ID = get_or_create_source(
    "Digital Business Africa",
    "https://www.digitalbusiness.africa", "fr", "web"
)


# ─────────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────────

BASE_URL      = "https://www.digitalbusiness.africa"
DB_PATH       = "digitalbusiness_africa.db"
DELAI         = 1.5    # secondes entre requêtes (respecte le serveur)
MAX_PAGES_RSS = 50     # WordPress pagine le RSS : ?paged=1 à N

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
}

# ─────────────────────────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────
# BASE DE DONNÉES SQLITE
# ─────────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────────
# UTILITAIRES
# ─────────────────────────────────────────────────────────────────

def parser_date_iso(iso_string):
    """'2026-04-10T11:21:35+00:00' → ('2026-04-10 11:21:35', 2026, 4, 10)"""
    if not iso_string:
        return None, None, None, None
    try:
        dt = datetime.fromisoformat(iso_string).astimezone(timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M:%S"), dt.year, dt.month, dt.day
    except Exception:
        return None, None, None, None


def parser_date_rss(rfc2822):
    """'Thu, 10 Apr 2026 11:21:35 +0000' → ('2026-04-10 11:21:35', 2026, 4, 10)"""
    if not rfc2822:
        return None, None, None, None
    try:
        dt = parsedate_to_datetime(rfc2822).astimezone(timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M:%S"), dt.year, dt.month, dt.day
    except Exception:
        return None, None, None, None


def detecter_langue(url):
    return "en" if "/en/" in url else "fr"


def is_article(url):
    """True si l'URL ressemble à un article (pas une page de navigation)."""
    if not url.startswith(BASE_URL):
        return False
    exclus = ["/category/", "/tag/", "/author/", "/page/", "/wp-",
              "?", "#", "/newsletter", "/feed", "/politique", "/a-propos"]
    if any(x in url for x in exclus):
        return False
    slug = url.replace(BASE_URL, "").strip("/").replace("/en/", "")
    return len(slug) > 5


def get(url, timeout=15):
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        r.raise_for_status()
        return r
    except requests.RequestException as e:
        log.warning(f"Erreur [{url[:80]}] : {e}")
        return None


def extraire_contenu(url):
    """Télécharge un article et retourne (contenu_texte, categorie)."""
    r = get(url)
    if r is None:
        return "", None
    soup = BeautifulSoup(r.text, "html.parser")

    corps = (soup.find("div", class_="entry-content")
             or soup.find("div", class_="post-content")
             or soup.find("article"))
    contenu = ""
    if corps:
        for t in corps.find_all(["script", "style", "nav", "aside", "figure", "form"]):
            t.decompose()
        contenu = corps.get_text(separator="\n", strip=True)[:8000]

    cat = soup.find("a", rel="category tag")
    categorie = cat.get_text(strip=True) if cat else None

    return contenu, categorie


def extraire_meta(url):
    """Extrait titre + date depuis les balises meta d'un article."""
    r = get(url)
    if r is None:
        return None, None, None, None, None
    soup = BeautifulSoup(r.text, "html.parser")

    og = soup.find("meta", property="og:title")
    titre = og.get("content", "").replace(" - Digital Business Africa", "").strip() if og else None

    meta_date = soup.find("meta", property="article:published_time")
    iso = meta_date.get("content", "") if meta_date else ""
    date_pub, annee, mois, jour = parser_date_iso(iso)

    return titre, date_pub, annee, mois, jour


# ─────────────────────────────────────────────────────────────────
# MÉTHODE 1 — FLUX RSS
# ─────────────────────────────────────────────────────────────────

def collecter_via_rss(date_limite, max_pages=MAX_PAGES_RSS):
    log.info("── Méthode RSS ──────────────────────────────")
    nouveaux = 0

    for base_feed, langue_feed in [
        (BASE_URL + "/feed/",    "fr"),
        (BASE_URL + "/en/feed/", "en"),
    ]:
        log.info(f"  Flux {langue_feed.upper()} : {base_feed}")

        for page in range(1, max_pages + 1):
            url_feed = base_feed if page == 1 else f"{base_feed}?paged={page}"
            r = get(url_feed)
            if r is None:
                log.warning("  Flux inaccessible — vérifier la connexion réseau")
                break

            soup = BeautifulSoup(r.content, "xml")
            items = soup.find_all("item")
            if not items:
                log.info(f"  Fin du flux à la page {page}")
                break

            stop_flux = False
            for item in items:
                url      = getattr(item.find("link") or item.find("guid"), "text", "").strip()
                titre    = getattr(item.find("title"), "text", "").strip()
                date_rss = getattr(item.find("pubDate"), "text", "").strip()
                resume   = BeautifulSoup(
                    getattr(item.find("description"), "text", "") or "", "html.parser"
                ).get_text(strip=True)[:500]
                categorie = getattr(item.find("category"), "text", "").strip()

                date_pub, annee, mois, jour = parser_date_rss(date_rss)

                # Filtre temporel — arrêt anticipé si article trop ancien
                if date_limite and date_pub:
                    dt = datetime.strptime(date_pub, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                    if dt < date_limite:
                        log.info(f"  ↩ Article de {date_pub} < limite — flux terminé")
                        stop_flux = True
                        break

                if not url or url_existe(url):
                    continue

                contenu, cat_page = extraire_contenu(url)

                sauvegarder_article(SOURCE_ID, {
                    "url": url, "titre": titre,
                    "date_publication": date_pub, "annee": annee, "mois": mois, "jour": jour,
                    "categorie": categorie or cat_page, "langue": detecter_langue(url),
                    "resume": resume, "contenu": contenu,
                    "methode_collecte": "rss",
                    "date_scraping": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                })
                nouveaux += 1
                log.info(f"  ✓ {titre[:65]} | {date_pub}")
                time.sleep(DELAI)

            if stop_flux:
                break
            time.sleep(DELAI)

    return nouveaux


# ─────────────────────────────────────────────────────────────────
# MÉTHODE 2 — SITEMAP XML
# ─────────────────────────────────────────────────────────────────

def collecter_via_sitemap(date_limite):
    log.info("── Méthode Sitemap ──────────────────────────")
    nouveaux = 0

    for i in range(1, 200):
        url_sitemap = f"{BASE_URL}/wp-sitemap-posts-post-{i}.xml"
        r = get(url_sitemap)
        if r is None:
            log.info(f"  Fin des sitemaps (index {i})")
            break

        soup = BeautifulSoup(r.content, "xml")
        urls = [loc.text.strip() for loc in soup.find_all("loc")]
        if not urls:
            break

        log.info(f"  Sitemap {i} : {len(urls)} URLs")

        for url in urls:
            if not is_article(url) or url_existe(url):
                continue

            titre, date_pub, annee, mois, jour = extraire_meta(url)

            if date_limite and date_pub:
                dt = datetime.strptime(date_pub, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                if dt < date_limite:
                    continue

            contenu, categorie = extraire_contenu(url)

            sauvegarder_article(SOURCE_ID, {
                "url": url, "titre": titre,
                "date_publication": date_pub, "annee": annee, "mois": mois, "jour": jour,
                "categorie": categorie, "langue": detecter_langue(url),
                "resume": None, "contenu": contenu,
                "methode_collecte": "sitemap",
                "date_scraping": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            })
            nouveaux += 1
            log.info(f"  ✓ {(titre or url)[:65]} | {date_pub}")
            time.sleep(DELAI)

        time.sleep(DELAI)

    return nouveaux


# ─────────────────────────────────────────────────────────────────
# SCRAPER PRINCIPAL
# ─────────────────────────────────────────────────────────────────

def scraper(date_depuis=None, methode="auto", mode_test=False):
    date_limite = None
    if date_depuis:
        date_limite = datetime.strptime(date_depuis, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        log.info(f"Filtre actif : articles publiés depuis le {date_depuis}")

    total = 0

    if methode in ("auto", "rss"):
        n = collecter_via_rss(date_limite, max_pages=1 if mode_test else MAX_PAGES_RSS)
        total += n
        log.info(f"RSS → {n} article(s) collecté(s)")

    if methode in ("auto", "sitemap") and not mode_test:
        n = collecter_via_sitemap(date_limite)
        total += n
        log.info(f"Sitemap → {n} article(s) collecté(s)")

    log.info(f"\n{'='*55}")
    log.info(f"Collecte terminée — {total} nouvel(s) article(s)")


# ─────────────────────────────────────────────────────────────────
# API DE REQUÊTE PAR DATE (pour le pipeline RAG)
# ─────────────────────────────────────────────────────────────────

def requete_par_date(db_path=DB_PATH, date_debut=None, date_fin=None,
                     langue=None, annee=None, mois=None, limit=50):
    """
    Interroge la base par date et retourne une liste de dicts.

    Exemples
    --------
    requete_par_date(date_debut='2025-01-01', date_fin='2025-12-31', langue='fr')
    requete_par_date(annee=2026, mois=3)
    requete_par_date(limit=10)
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cond, params = [], []

    if date_debut: cond.append("date_publication >= ?");        params.append(date_debut)
    if date_fin:   cond.append("date_publication <= ?");        params.append(date_fin + " 23:59:59")
    if langue:     cond.append("langue = ?");                   params.append(langue)
    if annee:      cond.append("annee = ?");                    params.append(annee)
    if mois:       cond.append("mois = ?");                     params.append(mois)

    where = ("WHERE " + " AND ".join(cond)) if cond else ""
    rows = conn.execute(
        f"SELECT * FROM articles {where} ORDER BY date_publication DESC LIMIT ?",
        params + [limit]
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def stats_db(db_path=DB_PATH):
    """Statistiques rapides sur la base collectée."""
    conn = sqlite3.connect(db_path)
    s = {
        "total":       conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0],
        "par_langue":  dict(conn.execute("SELECT langue, COUNT(*) FROM articles GROUP BY langue").fetchall()),
        "par_annee":   dict(conn.execute("SELECT annee, COUNT(*) FROM articles GROUP BY annee ORDER BY annee").fetchall()),
        "plus_recent": conn.execute("SELECT MAX(date_publication) FROM articles").fetchone()[0],
        "plus_ancien": conn.execute("SELECT MIN(date_publication) FROM articles").fetchone()[0],
    }
    conn.close()
    return s


# ─────────────────────────────────────────────────────────────────
# POINT D'ENTRÉE CLI
# ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Scraper Digital Business Africa → SQLite")
    ap.add_argument("--depuis",   metavar="YYYY-MM-DD", help="Date de début de collecte")
    ap.add_argument("--methode",  choices=["auto", "rss", "sitemap"], default="auto")
    ap.add_argument("--test",     action="store_true", help="1 page RSS seulement")
    ap.add_argument("--db",       default=DB_PATH)
    ap.add_argument("--stats",    action="store_true", help="Afficher les statistiques de la base")
    args = ap.parse_args()

    if args.stats:
        s = stats_db(args.db)
        print(f"\n{'─'*40}")
        print(f"Base          : {args.db}")
        print(f"Total         : {s['total']} articles")
        print(f"Par langue    : {s['par_langue']}")
        print(f"Par année     : {s['par_annee']}")
        print(f"Plus récent   : {s['plus_recent']}")
        print(f"Plus ancien   : {s['plus_ancien']}")
        print(f"{'─'*40}")
    else:
        scraper(date_depuis=args.depuis, methode=args.methode, mode_test=args.test)
