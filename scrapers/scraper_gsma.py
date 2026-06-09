"""
Scraper — GSMA (gsma.com)
==========================
Collecte les press releases du newsroom et les ressources Mobile for Development.

STRUCTURE DU SITE
─────────────────
GSMA possède deux espaces distincts :

  1. Newsroom WordPress (gsma.com/newsroom/)
     - Press releases : /newsroom/press-releases/page/N/
     - API REST WP    : /newsroom/wp-json/wp/v2/posts?per_page=12&page=N
     - Format date    : texte ('Tuesday 8 April, 2025') ou meta og:article:published_time

  2. Mobile for Development (gsma.com/solutions-and-impact/connectivity-for-good/mobile-for-development/)
     - Blog           : .../blog/
     - Ressources     : .../gsma_resources/
     - Pagination     : paramètre ?paged=N ou chargement AJAX
     - Format date    : texte dans le corps de l'article

Stratégie :
  - Newsroom   : API REST WP en priorité, fallback HTML /page/N/
  - MfD        : scraping HTML (pas d'API connue)

NOTE RÉSEAU
───────────
Bloqué depuis serveurs distants (403). Exécuter depuis poste DIIF.
Le newsroom WordPress est accessible depuis le poste local.
Les pages MfD (resources, blog) peuvent être partiellement bloquées —
le scraper gère les erreurs gracieusement.

USAGE
─────
    python scraper_gsma.py                       # collecte complète
    python scraper_gsma.py --depuis 2023-01-01   # depuis une date
    python scraper_gsma.py --type newsroom        # newsroom uniquement
    python scraper_gsma.py --type mfd             # Mobile for Development uniquement
    python scraper_gsma.py --test                 # 1 page par type
    python scraper_gsma.py --stats                # statistiques base
"""

import requests
from bs4 import BeautifulSoup
import sqlite3
import time
import argparse
import logging
import re
from datetime import datetime, timezone

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from base_scraper import get_or_create_source, url_existe, sauvegarder_article, now_iso

SOURCE_ID = get_or_create_source(
    "GSMA", "https://www.gsma.com/newsroom", "en", "web"
)
# ─────────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────────

BASE_NEWSROOM = "https://www.gsma.com/newsroom"
BASE_MFD      = "https://www.gsma.com/solutions-and-impact/connectivity-for-good/mobile-for-development"
DB_PATH       = "gsma.db"
DELAI         = 1.5

SOURCES = {
    "newsroom": {
        "liste_html": f"{BASE_NEWSROOM}/press-releases/",
        "pagination": "page/{page}/",           # /press-releases/page/2/
        "api_wp":     f"{BASE_NEWSROOM}/wp-json/wp/v2/posts?per_page=12&page={{page}}&_fields=id,title,date,link,excerpt",
        "prefixes":   ["/newsroom/press-release/"],
        "type":       "press_release",
    },
    # NOTE : mfd_blog et mfd_resources retirés — pages JavaScript pur,
    # inaccessibles via requests/BeautifulSoup.
    # Les publications MfD (State of the Industry, etc.) sont disponibles
    # sur FinDev Gateway (source 2), déjà couverte.
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.gsma.com/",
}

# Mois anglais → numéro
MOIS = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4,
    "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
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
# BASE DE DONNÉES
# ─────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────
# UTILITAIRES
# ─────────────────────────────────────────────────────────────────

def parser_date_iso(iso_string):
    """'2025-04-08T10:00:00+00:00' → ('2025-04-08 10:00:00', 2025, 4, 8)"""
    if not iso_string:
        return None, None, None, None
    try:
        dt = datetime.fromisoformat(iso_string).astimezone(timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M:%S"), dt.year, dt.month, dt.day
    except Exception:
        return None, None, None, None


def parser_date_texte(texte):
    """
    Parse les dates texte du GSMA newsroom.
    Formats : 'Tuesday 8 April, 2025' | 'Wednesday January 17, 2024' | '19 March 2024'
    """
    if not texte:
        return None, None, None, None
    texte = texte.strip().lower()

    # Supprimer le jour de la semaine s'il est présent
    for jour_sem in ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]:
        texte = texte.replace(jour_sem, "").strip().strip(",").strip()

    # Format : "8 april, 2025" ou "8 april 2025"
    m = re.search(r'(\d{1,2})\s+([a-z]+)[,\s]+(\d{4})', texte)
    if m:
        jour = int(m.group(1))
        mois = MOIS.get(m.group(2)[:9])
        annee = int(m.group(3))
        if mois:
            return f"{annee:04d}-{mois:02d}-{jour:02d} 00:00:00", annee, mois, jour

    # Format : "january 17, 2024" ou "march 2024"
    m = re.search(r'([a-z]+)\s+(\d{1,2})[,\s]+(\d{4})', texte)
    if m:
        mois = MOIS.get(m.group(1)[:9])
        jour = int(m.group(2))
        annee = int(m.group(3))
        if mois:
            return f"{annee:04d}-{mois:02d}-{jour:02d} 00:00:00", annee, mois, jour

    # Format ISO : "2024-01-17"
    m = re.search(r'(\d{4})-(\d{2})-(\d{2})', texte)
    if m:
        annee, mois, jour = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return f"{annee:04d}-{mois:02d}-{jour:02d} 00:00:00", annee, mois, jour

    return None, None, None, None


def get(url, json_mode=False, timeout=12):
    h = {**HEADERS, "Accept": "application/json"} if json_mode else HEADERS
    try:
        r = requests.get(url, headers=h, timeout=timeout)
        r.raise_for_status()
        return r
    except requests.RequestException as e:
        log.warning(f"Erreur [{url[-65:]}] : {e}")
        return None


def trouver_date_article(soup):
    """Cherche la date dans une page article GSMA selon plusieurs stratégies."""
    # 1. Meta og:article:published_time (WordPress)
    for prop in ["article:published_time", "og:updated_time"]:
        m = soup.find("meta", property=prop)
        if m:
            return parser_date_iso(m.get("content", ""))

    # 2. Balise <time datetime="...">
    t = soup.find("time", attrs={"datetime": True})
    if t:
        return parser_date_iso(t["datetime"])

    # 3. Texte de date visible (newsroom GSMA : "Tuesday 8 April, 2025")
    for pattern in [
        r'\b(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s+\d{1,2}\s+\w+,?\s+\d{4}\b',
        r'\b\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)[,\s]+\d{4}\b',
        r'\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2}[,\s]+\d{4}\b',
    ]:
        match = re.search(pattern, soup.get_text(), re.IGNORECASE)
        if match:
            result = parser_date_texte(match.group())
            if result[0]:
                return result

    return None, None, None, None


# ─────────────────────────────────────────────────────────────────
# EXTRACTION D'UN ARTICLE
# ─────────────────────────────────────────────────────────────────

def extraire_article(url, type_contenu, resume_prefill=None):
    r = get(url)
    if r is None:
        return None

    soup = BeautifulSoup(r.text, "html.parser")

    # — Titre —
    titre = None
    og = soup.find("meta", property="og:title")
    if og:
        titre = og.get("content", "").strip()
        # Nettoyer les suffixes GSMA
        for suffix in [" - Newsroom", " | Mobile for Development", " - GSMA"]:
            titre = titre.replace(suffix, "").strip()
    if not titre:
        h1 = soup.find("h1")
        titre = h1.get_text(strip=True) if h1 else None

    # — Date —
    date_pub, annee, mois, jour = trouver_date_article(soup)

    # — Résumé —
    resume = resume_prefill
    if not resume:
        m = soup.find("meta", attrs={"name": "description"}) or \
            soup.find("meta", property="og:description")
        if m:
            resume = m.get("content", "").strip()

    # — Contenu —
    contenu = ""
    corps = (
        soup.find("div", class_=re.compile(r"entry-content|post-content|article-body|content-body"))
        or soup.find("article")
        or soup.find("main")
    )
    if corps:
        for tag in corps.find_all(["script", "style", "nav", "aside", "form",
                                    "header", "footer", "figure"]):
            tag.decompose()
        contenu = corps.get_text(separator="\n", strip=True)[:8000]

    return {
        "url": url,
        "titre": titre,
        "date_publication": date_pub,
        "annee": annee,
        "mois": mois,
        "jour": jour,
        "type_contenu": type_contenu,
        "langue": "en",
        "resume": resume,
        "contenu": contenu,
        "methode_collecte": "html",
        "date_scraping": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
    }


# ─────────────────────────────────────────────────────────────────
# MÉTHODE 1 — API REST WORDPRESS (newsroom uniquement)
# ─────────────────────────────────────────────────────────────────

def collecter_via_api_wp(type_nom, config, date_limite, mode_test):
    if not config.get("api_wp"):
        return 0, False

    log.info("  → Tentative API REST WordPress")
    nouveaux = 0
    page = 1

    while True:
        url_api = config["api_wp"].format(page=page)
        r = get(url_api, json_mode=True, timeout=8)
        if r is None:
            return nouveaux, False

        try:
            items = r.json()
        except Exception:
            return nouveaux, False

        if not items or not isinstance(items, list):
            break

        stop = False
        for item in items:
            url = item.get("link", "")
            titre = BeautifulSoup(
                item.get("title", {}).get("rendered", ""), "html.parser"
            ).get_text(strip=True)
            date_iso = item.get("date_gmt", item.get("date", ""))
            if not date_iso.endswith("+00:00"):
                date_iso += "+00:00"
            resume_html = item.get("excerpt", {}).get("rendered", "")
            resume = BeautifulSoup(resume_html, "html.parser").get_text(strip=True)[:500]

            date_pub, annee, mois, jour = parser_date_iso(date_iso)

            if date_limite and date_pub:
                dt = datetime.strptime(date_pub, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                if dt < date_limite:
                    log.info(f"  ↩ Trop ancien ({date_pub}) — arrêt")
                    stop = True
                    break

            if not url or url_existe(url):
                continue

            article = extraire_article(url, config["type"], resume_prefill=resume)
            if article is None:
                continue

            article["date_publication"] = date_pub
            article["annee"] = annee
            article["mois"] = mois
            article["jour"] = jour
            article["methode_collecte"] = "api_wp"

            sauvegarder_article(SOURCE_ID, article)
            nouveaux += 1
            log.info(f"  ✓ {titre[:65]} | {date_pub}")
            time.sleep(DELAI)

        if stop or mode_test:
            break
        page += 1
        time.sleep(DELAI)

    return nouveaux, True


# ─────────────────────────────────────────────────────────────────
# MÉTHODE 2 — SCRAPING HTML
# ─────────────────────────────────────────────────────────────────

def collecter_via_html(type_nom, config, date_limite, mode_test):
    log.info("  → Scraping HTML")
    nouveaux = 0
    page = 1

    while True:
        if page == 1:
            url_liste = config["liste_html"]
        else:
            pag = config["pagination"].format(page=page)
            if pag.startswith("?"):
                url_liste = config["liste_html"] + pag
            else:
                url_liste = config["liste_html"] + pag

        log.info(f"  Page {page} : {url_liste}")
        r = get(url_liste)
        if r is None:
            break

        soup = BeautifulSoup(r.text, "html.parser")

        urls_page = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if not href.startswith("http"):
                href = "https://www.gsma.com" + href if href.startswith("/") else None
            if not href:
                continue
            chemin = href.replace("https://www.gsma.com", "")
            if any(chemin.startswith(p) for p in config["prefixes"]):
                if len(chemin.strip("/")) > 10 and href not in urls_page:
                    urls_page.append(href)

        if not urls_page:
            log.info("  Aucun article — fin pagination")
            break

        log.info(f"  {len(urls_page)} article(s)")
        stop = False

        for url in urls_page:
            if url_existe(url):
                continue
            article = extraire_article(url, config["type"])
            if article is None:
                continue

            if date_limite and article["date_publication"]:
                dt = datetime.strptime(
                    article["date_publication"], "%Y-%m-%d %H:%M:%S"
                ).replace(tzinfo=timezone.utc)
                if dt < date_limite:
                    log.info(f"  ↩ Trop ancien ({article['date_publication']}) — arrêt")
                    stop = True
                    break

            sauvegarder_article(SOURCE_ID, article)
            nouveaux += 1
            log.info(f"  ✓ {(article['titre'] or '')[:65]} | {article['date_publication']}")
            time.sleep(DELAI)

        if stop or mode_test:
            break
        page += 1
        time.sleep(DELAI)

    return nouveaux


# ─────────────────────────────────────────────────────────────────
# SCRAPER PRINCIPAL
# ─────────────────────────────────────────────────────────────────

def scraper(date_depuis=None, types=None, mode_test=False):

    date_limite = None
    if date_depuis:
        date_limite = datetime.strptime(date_depuis, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        log.info(f"Filtre actif : articles depuis le {date_depuis}")

    sources_actives = {
        k: v for k, v in SOURCES.items()
        if types is None or k in types
    }

    total = 0
    for type_nom, config in sources_actives.items():
        log.info(f"\n── {type_nom.upper()} ──")

        # Newsroom : essayer API REST d'abord
        if config.get("api_wp"):
            n, ok = collecter_via_api_wp(type_nom, config, date_limite, mode_test)
            if ok:
                total += n
                log.info(f"→ {type_nom} : {n} article(s) [API REST]")
                continue
            log.info("  API indisponible → scraping HTML")

        # MfD ou fallback : scraping HTML
        n = collecter_via_html(type_nom, config, date_limite, mode_test)
        total += n
        log.info(f"→ {type_nom} : {n} article(s) [HTML]")

    log.info(f"\n{'='*55}")
    log.info(f"Collecte terminée — {total} nouvel(s) article(s)")


# ─────────────────────────────────────────────────────────────────
# API DE REQUÊTE PAR DATE
# ─────────────────────────────────────────────────────────────────

def requete_par_date(db_path=DB_PATH, date_debut=None, date_fin=None,
                     type_contenu=None, annee=None, mois=None, limit=50):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cond, params = [], []

    if date_debut:   cond.append("date_publication >= ?"); params.append(date_debut)
    if date_fin:     cond.append("date_publication <= ?"); params.append(date_fin + " 23:59:59")
    if type_contenu: cond.append("type_contenu = ?");     params.append(type_contenu)
    if annee:        cond.append("annee = ?");            params.append(annee)
    if mois:         cond.append("mois = ?");             params.append(mois)

    where = ("WHERE " + " AND ".join(cond)) if cond else ""
    rows = conn.execute(
        f"SELECT * FROM articles {where} ORDER BY date_publication DESC LIMIT ?",
        params + [limit]
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def stats_db(db_path=DB_PATH):
    conn = sqlite3.connect(db_path)
    s = {
        "total":       conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0],
        "par_type":    dict(conn.execute("SELECT type_contenu, COUNT(*) FROM articles GROUP BY type_contenu").fetchall()),
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
    ap = argparse.ArgumentParser(description="Scraper GSMA → SQLite (DIIF/BEAC)")
    ap.add_argument("--depuis",  metavar="YYYY-MM-DD")
    ap.add_argument("--type",    nargs="+", choices=list(SOURCES.keys()))
    ap.add_argument("--test",    action="store_true")
    ap.add_argument("--db",      default=DB_PATH)
    ap.add_argument("--stats",   action="store_true")
    args = ap.parse_args()

    if args.stats:
        s = stats_db(args.db)
        print(f"\n{'─'*40}")
        print(f"Base        : {args.db}")
        print(f"Total       : {s['total']} articles")
        print(f"Par type    : {s['par_type']}")
        print(f"Par année   : {s['par_annee']}")
        print(f"Plus récent : {s['plus_recent']}")
        print(f"Plus ancien : {s['plus_ancien']}")
        print(f"{'─'*40}")
    else:
        scraper(date_depuis=args.depuis, types=args.type, mode_test=args.test)
