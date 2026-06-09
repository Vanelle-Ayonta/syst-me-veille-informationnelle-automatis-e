"""
Scraper — AFI Global (afi-global.org)
======================================
Collecte news, publications et opinions et les stocke en SQLite.

STRUCTURE DU SITE
─────────────────
AFI est un site WordPress 6.x avec un bouton "Load more" sur les pages liste.
Les articles sont initialement chargés en HTML statique (premier lot visible
sans JavaScript), puis des appels AJAX chargent la suite.

Stratégie retenue : scraping HTML des pages + API REST WordPress pour pagination.
  - API REST WP  : /wp-json/wp/v2/posts?page=N&per_page=10
  - Fallback     : pages HTML avec ?paged=N si l'API est bloquée

Types de contenus :
  - News         : /newsroom/news/         → actualités institutionnelles
  - Publications : /knowledge-center/publications/ → rapports, guides (500+)
  - Opinion      : /newsroom/opinion/      → analyses d'experts
  - CEO          : /newsroom/ceo-reflections/ → réflexions du DG

Format de date : ISO 8601 dans meta article:published_time (WordPress)

NOTE RÉSEAU
───────────
Bloqué depuis serveurs distants (403). Exécuter depuis poste DIIF.

USAGE
─────
    python scraper_afi.py                       # collecte complète
    python scraper_afi.py --depuis 2023-01-01   # depuis une date
    python scraper_afi.py --type news           # un seul type
    python scraper_afi.py --test                # 1 page par type
    python scraper_afi.py --stats               # statistiques base
"""

import requests
from bs4 import BeautifulSoup
import sqlite3
import time
import argparse
import logging
import re
import json
from datetime import datetime, timezone

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from base_scraper import get_or_create_source, url_existe, sauvegarder_article, now_iso

SOURCE_ID = get_or_create_source(
    "AFI Global", "https://afi-global.org", "en", "web"
)

# ─────────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────────

BASE_URL = "https://afi-global.org"
DB_PATH  = "afi_global.db"
DELAI    = 1.5

SOURCES = {
    "news": {
        "liste_html":  "/newsroom/news/",
        # Plusieurs candidats à essayer dans l'ordre — le premier qui répond 200 est retenu
        "api_wp_candidates": [
            # posts en premier : confirmé fonctionnel au test
            "/wp-json/wp/v2/posts?per_page=12&page={page}&_fields=id,title,date,link,excerpt",
            "/wp-json/wp/v2/news?per_page=12&page={page}&_fields=id,title,date,link,excerpt",
            "/wp-json/wp/v2/afi_news?per_page=12&page={page}&_fields=id,title,date,link,excerpt",
        ],
        "api_wp": "/wp-json/wp/v2/posts?per_page=12&page={page}&_fields=id,title,date,link,excerpt",
        "prefixes":    ["/news/"],
        "type_wp":     "news",
    },
    "publication": {
        "liste_html":  "/knowledge-center/publications/",
        "api_wp":      "/wp-json/wp/v2/publication?per_page=12&page={page}&_fields=id,title,date,link,excerpt",
        "prefixes":    ["/publication/"],
        "type_wp":     "publication",
    },
    "opinion": {
        "liste_html":  "/newsroom/opinion/",
        "api_wp":      "/wp-json/wp/v2/posts?per_page=12&page={page}&_fields=id,title,date,link,excerpt",
        "prefixes":    ["/opinion/"],
        "type_wp":     "post",
    },
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://afi-global.org/",
}

HEADERS_JSON = {**HEADERS, "Accept": "application/json"}

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
    """'2024-04-09T00:00:27+00:00' → ('2024-04-09 00:00:27', 2024, 4, 9)"""
    if not iso_string:
        return None, None, None, None
    try:
        dt = datetime.fromisoformat(iso_string).astimezone(timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M:%S"), dt.year, dt.month, dt.day
    except Exception:
        return None, None, None, None


def get(url, json_mode=False, timeout=15):
    h = HEADERS_JSON if json_mode else HEADERS
    try:
        r = requests.get(url, headers=h, timeout=timeout)
        r.raise_for_status()
        return r
    except requests.RequestException as e:
        log.warning(f"Erreur [{url[-70:]}] : {e}")
        return None


# ─────────────────────────────────────────────────────────────────
# EXTRACTION D'UN ARTICLE
# ─────────────────────────────────────────────────────────────────

def extraire_article(url, type_contenu, resume_prefill=None):
    """Télécharge et parse un article AFI. Retourne un dict ou None."""
    r = get(url)
    if r is None:
        return None

    soup = BeautifulSoup(r.text, "html.parser")

    # — Titre —
    # AFI utilise Elementor : le h1 est souvent vide.
    # Source fiable : og:title ou balise <title>.
    titre = None
    og_title = soup.find("meta", property="og:title")
    if og_title:
        titre = og_title.get("content", "").replace(
            " - Alliance for Financial Inclusion", "").strip()
    if not titre:
        h1 = soup.find("h1")
        titre = h1.get_text(strip=True) if h1 else None
    if not titre:
        title_tag = soup.find("title")
        if title_tag:
            titre = title_tag.get_text(strip=True).replace(
                " - Alliance for Financial Inclusion", "").strip()

    # — Date (meta WordPress) —
    meta_date = soup.find("meta", property="article:published_time")
    iso = meta_date.get("content", "") if meta_date else ""
    date_pub, annee, mois, jour = parser_date_iso(iso)

    # — Résumé —
    resume = resume_prefill
    if not resume:
        meta_desc = soup.find("meta", attrs={"name": "description"})
        if meta_desc:
            resume = meta_desc.get("content", "").strip()

    # — Contenu principal —
    contenu = ""
    corps = (
        soup.find("div", class_=re.compile(r"entry-content|post-content|single-content"))
        or soup.find("article")
        or soup.find("main")
    )
    if corps:
        for tag in corps.find_all(["script", "style", "nav", "aside", "form",
                                    "header", "footer", "figure"]):
            tag.decompose()
        contenu = corps.get_text(separator="\n", strip=True)[:8000]

    # — Région AFI mentionnée —
    region = None
    regions_afi = ["Africa", "Sub-Saharan", "CEMAC", "West Africa", "Central Africa",
                   "Latin America", "Asia", "Pacific", "Middle East", "Europe"]
    texte_page = soup.get_text()
    for reg in regions_afi:
        if reg.lower() in texte_page.lower():
            region = reg
            break

    return {
        "url": url,
        "titre": titre,
        "date_publication": date_pub,
        "annee": annee,
        "mois": mois,
        "jour": jour,
        "type_contenu": type_contenu,
        "region": region,
        "langue": "en",
        "resume": resume,
        "contenu": contenu,
        "methode_collecte": "html",
        "date_scraping": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
    }


# ─────────────────────────────────────────────────────────────────
# MÉTHODE 1 — API REST WORDPRESS
# ─────────────────────────────────────────────────────────────────

def collecter_via_api_wp(type_nom, config, date_limite, mode_test):
    """
    Utilise l'API REST WordPress /wp-json/wp/v2/... pour paginer.
    Plus fiable que le scraping HTML pour la pagination.
    Retourne (nb_articles, succès_bool).
    """
    log.info(f"  → Tentative API REST WordPress")
    nouveaux = 0
    page = 1

    # Auto-découverte : essayer les candidats pour trouver le bon endpoint
    api_template = config.get("api_wp", "")
    if "api_wp_candidates" in config:
        for candidate in config["api_wp_candidates"]:
            test_url = BASE_URL + candidate.format(page=1)
            r_test = get(test_url, json_mode=True, timeout=5)
            if r_test is not None:
                try:
                    data = r_test.json()
                    if isinstance(data, list):
                        api_template = candidate
                        log.info(f"  API trouvée : {candidate.split('?')[0]}")
                        break
                except Exception:
                    pass
        else:
            log.warning("  Aucun endpoint API valide trouvé")
            return nouveaux, False

    while True:
        url_api = BASE_URL + api_template.format(page=page)
        r = get(url_api, json_mode=True)

        if r is None:
            log.warning("  API REST inaccessible")
            return nouveaux, False

        try:
            items = r.json()
        except Exception:
            return nouveaux, False

        if not items or not isinstance(items, list):
            log.info(f"  Fin de l'API à la page {page}")
            break

        stop = False
        for item in items:
            url = item.get("link", "")
            titre = BeautifulSoup(
                item.get("title", {}).get("rendered", ""), "html.parser"
            ).get_text(strip=True)
            date_iso = item.get("date_gmt", item.get("date", ""))
            resume_html = item.get("excerpt", {}).get("rendered", "")
            resume = BeautifulSoup(resume_html, "html.parser").get_text(strip=True)[:500]

            date_pub, annee, mois, jour = parser_date_iso(date_iso + "+00:00" if "+" not in date_iso else date_iso)

            if date_limite and date_pub:
                dt = datetime.strptime(date_pub, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                if dt < date_limite:
                    log.info(f"  ↩ Trop ancien ({date_pub}) — arrêt")
                    stop = True
                    break

            if not url or url_existe(url):
                continue

            # Récupérer le contenu complet
            article = extraire_article(url, type_nom, resume_prefill=resume)
            if article is None:
                continue

            # Compléter avec les données de l'API (plus fiables)
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
# MÉTHODE 2 — SCRAPING HTML (fallback)
# ─────────────────────────────────────────────────────────────────

def collecter_via_html(type_nom, config, date_limite, mode_test):
    """
    Scrape les pages HTML de liste avec ?paged=N.
    Fallback si l'API REST est bloquée.
    """
    log.info(f"  → Fallback scraping HTML")
    nouveaux = 0
    page = 1

    while True:
        url_liste = BASE_URL + config["liste_html"] + (f"?paged={page}" if page > 1 else "")
        log.info(f"  Page {page} : {url_liste}")

        r = get(url_liste)
        if r is None:
            break

        soup = BeautifulSoup(r.text, "html.parser")

        # Extraire les URLs d'articles
        urls_page = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if href.startswith("/"):
                href = BASE_URL + href
            if not href.startswith(BASE_URL):
                continue
            chemin = href.replace(BASE_URL, "")
            if any(chemin.startswith(p) for p in config["prefixes"]):
                slug = chemin.strip("/")
                if len(slug) > 8 and href not in urls_page:
                    urls_page.append(href)

        if not urls_page:
            log.info("  Aucun article trouvé — fin de pagination")
            break

        log.info(f"  {len(urls_page)} article(s) sur cette page")
        stop = False

        for url in urls_page:
            if url_existe(url):
                continue

            article = extraire_article(url, type_nom)
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

        n, api_ok = collecter_via_api_wp(type_nom, config, date_limite, mode_test)

        if not api_ok:
            log.info("  API indisponible → scraping HTML")
            n = collecter_via_html(type_nom, config, date_limite, mode_test)

        total += n
        log.info(f"→ {type_nom} : {n} article(s) collecté(s)")

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
    ap = argparse.ArgumentParser(description="Scraper AFI Global → SQLite (DIIF/BEAC)")
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
