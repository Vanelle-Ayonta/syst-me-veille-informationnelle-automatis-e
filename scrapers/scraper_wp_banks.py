"""
scraper_wp_banks.py — Scraper WordPress générique pour banques centrales
=========================================================================
Couvre :
  - Banque du Canada     (bankofcanada.ca)     — WordPress + RSS riche
  - Banque du Kenya CBK  (centralbank.go.ke)   — WordPress + API REST
  - Bank of Ghana BoG    (bog.gov.gh)          — WordPress + RSS + API REST

Toutes ces sources utilisent WordPress — la même logique s'applique.
Stratégie : API REST WP en priorité → RSS WordPress → fallback HTML.
Filtre thématique actif (liste de mots-clés inclusion/innovation/éducation financière).

USAGE
─────
    python scraper_wp_banks.py --source all --test
    python scraper_wp_banks.py --source canada --test
    python scraper_wp_banks.py --source kenya --test
    python scraper_wp_banks.py --source ghana --test
    python scraper_wp_banks.py --source all --depuis 2023-01-01
    python scraper_wp_banks.py --stats

NOTE RÉSEAU : Exécuter depuis poste DIIF (bloqué depuis serveurs distants).
"""

import requests
from bs4 import BeautifulSoup
import sqlite3
import time
import argparse
import logging
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from base_scraper import get_or_create_source, url_existe, sauvegarder_article

SOURCE_IDS = {
    "canada": get_or_create_source("Banque du Canada", "https://www.bankofcanada.ca", "en", "web"),
    "kenya":  get_or_create_source("Central Bank of Kenya", "https://www.centralbank.go.ke", "en", "web"),
    "ghana":  get_or_create_source("Bank of Ghana", "https://www.bog.gov.gh", "en", "web"),
}

# ─────────────────────────────────────────────────────────────────
# CONFIGURATION DES SOURCES
# ─────────────────────────────────────────────────────────────────

SOURCES = {
    "canada": {
        "nom":       "Banque du Canada",
        "base_url":  "https://www.bankofcanada.ca",
        "db":        "banque_canada.db",
        "langue":    "en",
        "source":    "Bank of Canada",
        "filtrer":   True,   # filtre actif — mais RSS pubs très ciblé donc peu de faux positifs

        # API REST WordPress — plusieurs post_types
        "api_endpoints": [
            "/wp-json/wp/v2/posts?per_page=10&page={page}&_fields=id,title,date_gmt,link,excerpt",
        ],
        # RSS WordPress par type de publication
        "rss_feeds": [
            # Flux ciblés sur les types pertinents
            "/feed/?post_type=pubs&content_type=staff-working-papers",  # working papers
            "/feed/?post_type=pubs&content_type=staff-discussion-papers",  # discussion papers
            "/feed/?post_type=pubs",         # toutes publications
            "/feed/",                        # toutes actualités
        ],
        # Préfixes URLs articles valides
        "prefixes": ["/20", "/research/", "/publications/"],
        # Sections HTML en fallback
        "listes_html": [
            "/research/browse/",
            "/publications/",
        ],
    },
    "kenya": {
        "nom":       "Central Bank of Kenya",
        "base_url":  "https://www.centralbank.go.ke",
        "db":        "cbk_kenya.db",
        "langue":    "en",
        "source":    "Central Bank of Kenya",
        "filtrer":   True,

        "api_endpoints": [
            "/wp-json/wp/v2/posts?per_page=10&page={page}&_fields=id,title,date_gmt,link,excerpt",
        ],
        "rss_feeds": [
            "/feed/",
            "/category/press-releases/feed/",
        ],
        "prefixes": ["/category/", "/2024/", "/2025/", "/2026/", "/finaccess/"],
        "listes_html": [
            "/category/press-releases/",
            "/category/banking-sector/",
        ],
    },
    "ghana": {
        "nom":       "Bank of Ghana",
        "base_url":  "https://www.bog.gov.gh",
        "db":        "bog_ghana.db",
        "langue":    "en",
        "source":    "Bank of Ghana",
        "filtrer":   True,

        "api_endpoints": [
            # Essayer plusieurs custom post types
            "/wp-json/wp/v2/posts?per_page=10&page={page}&_fields=id,title,date_gmt,link,excerpt",
            "/wp-json/wp/v2/news?per_page=10&page={page}&_fields=id,title,date_gmt,link,excerpt",
        ],
        "rss_feeds": [
            "/feed/",
            "/news/feed/",
            "/press-release/feed/",
        ],
        "prefixes": ["/news/", "/press-release/", "/fintech-innovation/", "/all-news-page/"],
        "listes_html": [
            "/all-news-page/",
            "/press-release/",
            "/fintech-innovation/",
        ],
    },
}

# ─────────────────────────────────────────────────────────────────
# MOTS-CLÉS FILTRE THÉMATIQUE
# ─────────────────────────────────────────────────────────────────

MOTS_CLES = [
    # Inclusion financière
    "financial inclusion", "inclusion financière", "unbanked", "underbanked",
    "bancarisation", "microfinance", "microcredit", "microcrédit",
    "financial access", "access to finance", "mobile money", "mobile banking",
    "agent banking", "agent bancaire", "financial exclusion",
    # Innovation / Fintech
    "fintech", "digital payment", "paiement numérique", "paiement mobile",
    "mobile payment", "digital finance", "digital currency", "monnaie numérique",
    "cbdc", "central bank digital", "e-money", "monnaie électronique",
    "open banking", "open finance", "interoperability", "interopérabilité",
    "fast payment", "instant payment", "remittance", "money transfer",
    "digital wallet", "e-wallet", "qr code", "contactless",
    "neobank", "néobanque", "insurtech", "regtech",
    # Éducation financière
    "financial education", "éducation financière", "financial literacy",
    "culture financière", "educfi", "financial capability",
    # Géographie pertinente
    "africa", "afrique", "sub-saharan", "subsaharienne",
    "cemac", "uemoa", "ecowas", "cedeao", "east africa",
    "developing", "émergent", "emerging market",
    # Institutions
    "central bank", "banque centrale", "monetary policy", "financial stability",
    "payment system", "système de paiement",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,fr;q=0.8",
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────
# UTILITAIRES
# ─────────────────────────────────────────────────────────────────

def parser_date_iso(iso_string):
    if not iso_string:
        return None, None, None, None
    try:
        if "+" not in iso_string and "Z" not in iso_string:
            iso_string += "+00:00"
        dt = datetime.fromisoformat(iso_string).astimezone(timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M:%S"), dt.year, dt.month, dt.day
    except Exception:
        return None, None, None, None


def parser_date_rss(rfc2822):
    if not rfc2822:
        return None, None, None, None
    try:
        dt = parsedate_to_datetime(rfc2822).astimezone(timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M:%S"), dt.year, dt.month, dt.day
    except Exception:
        return None, None, None, None


def est_pertinent(titre, resume, filtrer=True):
    if not filtrer:
        return True
    texte = f"{titre} {resume}".lower()
    return any(mot in texte for mot in MOTS_CLES)


def get(url, json_mode=False, timeout=12, retries=2):
    h = {**HEADERS, "Accept": "application/json"} if json_mode else HEADERS
    for tentative in range(retries + 1):
        try:
            r = requests.get(url, headers=h, timeout=timeout)
            r.raise_for_status()
            return r
        except requests.RequestException as e:
            if tentative < retries:
                time.sleep(3)
            else:
                log.warning(f"Erreur [{url[-65:]}] : {e}")
                return None


def extraire_article(url, source_config, resume_prefill=None):
    r = get(url)
    if r is None:
        return None
    soup = BeautifulSoup(r.text, "html.parser")

    # Titre
    titre = None
    og = soup.find("meta", property="og:title")
    if og:
        titre = og.get("content", "")
        for suffix in [" - Bank of Canada", " - Banque du Canada",
                       " | CBK", " – Bank of Ghana", " - Bank of Ghana"]:
            titre = titre.replace(suffix, "")
        titre = titre.strip()
    if not titre:
        h1 = soup.find("h1")
        titre = h1.get_text(strip=True) if h1 else None

    # Date
    date_pub = annee = mois = jour = None
    meta_date = soup.find("meta", property="article:published_time")
    if meta_date:
        date_pub, annee, mois, jour = parser_date_iso(meta_date.get("content", ""))
    if not date_pub:
        t = soup.find("time", attrs={"datetime": True})
        if t:
            date_pub, annee, mois, jour = parser_date_iso(t["datetime"])
    if not date_pub:
        # Fallback : date dans l'URL WordPress /YYYY/MM/DD/
        m = re.search(r'/(\d{4})/(\d{2})/(\d{2})/', url)
        if m:
            a, mo, j = int(m.group(1)), int(m.group(2)), int(m.group(3))
            date_pub = f"{a:04d}-{mo:02d}-{j:02d} 00:00:00"
            annee, mois, jour = a, mo, j

    # Résumé
    resume = resume_prefill
    if not resume:
        m = soup.find("meta", attrs={"name": "description"}) or \
            soup.find("meta", property="og:description")
        if m:
            resume = m.get("content", "").strip()

    # Contenu
    contenu = ""
    corps = (
        soup.find("div", class_=re.compile(r"entry-content|post-content|article-content|node__content"))
        or soup.find("article") or soup.find("main")
    )
    if corps:
        for tag in corps.find_all(["script", "style", "nav", "aside", "form", "header", "footer"]):
            tag.decompose()
        contenu = corps.get_text(separator="\n", strip=True)[:8000]

    return {
        "url": url, "titre": titre,
        "date_publication": date_pub, "annee": annee, "mois": mois, "jour": jour,
        "type_contenu": "article",
        "langue": source_config["langue"],
        "resume": resume, "contenu": contenu,
        "source": source_config["source"],
        "methode_collecte": "html",
        "date_scraping": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
    }


# ─────────────────────────────────────────────────────────────────
# MÉTHODE 1 — API REST WORDPRESS
# ─────────────────────────────────────────────────────────────────

def collecter_via_api(source_id, config, date_limite, mode_test):
    log.info("  → Tentative API REST WordPress")

    for endpoint_tpl in config["api_endpoints"]:
        page = 1
        nouveaux = 0
        api_ok = False

        while True:
            url_api = config["base_url"] + endpoint_tpl.format(page=page)
            r = get(url_api, json_mode=True, timeout=5)  # timeout court pour détection rapide
            if r is None:
                break
            try:
                items = r.json()
            except Exception:
                break
            if not items or not isinstance(items, list):
                if page == 1:
                    break
                log.info(f"  Fin API à la page {page}")
                break

            api_ok = True
            stop = False

            for item in items:
                url = item.get("link", "")
                titre = BeautifulSoup(
                    item.get("title", {}).get("rendered", ""), "html.parser"
                ).get_text(strip=True)
                date_iso = item.get("date_gmt", item.get("date", ""))
                resume = BeautifulSoup(
                    item.get("excerpt", {}).get("rendered", ""), "html.parser"
                ).get_text(strip=True)[:500]

                date_pub, annee, mois, jour = parser_date_iso(date_iso)

                if not est_pertinent(titre, resume, config["filtrer"]):
                    continue

                if date_limite and date_pub:
                    dt = datetime.strptime(date_pub, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                    if dt < date_limite:
                        log.info(f"  ↩ Trop ancien ({date_pub}) — arrêt")
                        stop = True; break

                if not url or url_existe(url):
                    continue

                article = extraire_article(url, config, resume_prefill=resume)
                if article is None:
                    continue
                article.update({
                    "date_publication": date_pub, "annee": annee, "mois": mois,
                    "jour": jour, "methode_collecte": "api_wp"
                })
                sauvegarder_article(source_id, article)
                nouveaux += 1
                log.info(f"  ✓ {titre[:65]} | {date_pub}")
                time.sleep(1.5)

            if stop or mode_test or len(items) < 10:
                break
            page += 1
            time.sleep(1.5)

        if api_ok:
            return nouveaux, True

    return 0, False


# ─────────────────────────────────────────────────────────────────
# MÉTHODE 2 — RSS WORDPRESS
# ─────────────────────────────────────────────────────────────────

def collecter_via_rss(source_id, config, date_limite, mode_test):
    log.info("  → Flux RSS WordPress")
    nouveaux = 0

    for feed_idx, feed_path in enumerate(config["rss_feeds"]):
        # En mode test, on teste uniquement le premier flux
        if mode_test and feed_idx > 0:
            break
        url_rss = config["base_url"] + feed_path

        for page in range(1, 30):
            url_feed = url_rss if page == 1 else f"{url_rss}?paged={page}"
            r = get(url_feed)
            if r is None:
                break

            soup = BeautifulSoup(r.content, "xml")
            items = soup.find_all("item")
            if not items:
                break

            log.info(f"  RSS {feed_path} page {page} : {len(items)} items")
            stop = False
            if mode_test and page > 1:
                log.info("  [MODE TEST] Arrêt après 1 page RSS")
                break

            for item in items:
                url = getattr(item.find("link"), "text", "").strip()
                titre = getattr(item.find("title"), "text", "").strip()
                # Chercher la date dans plusieurs balises (pubDate, dc:date, date...)
                date_rss = ""
                for tag_name in ["pubDate", "dc:date", "date", "updated", "published"]:
                    el = item.find(tag_name)
                    if el and el.text.strip():
                        date_rss = el.text.strip()
                        break

                resume = BeautifulSoup(
                    getattr(item.find("description"), "text", "") or "", "html.parser"
                ).get_text(strip=True)[:500]

                date_pub, annee, mois, jour = parser_date_rss(date_rss)
                if not date_pub:
                    date_pub, annee, mois, jour = parser_date_iso(date_rss)

                if not est_pertinent(titre, resume, config["filtrer"]):
                    continue

                if date_limite and date_pub:
                    dt = datetime.strptime(date_pub, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                    if dt < date_limite:
                        stop = True; break

                if not url or url_existe(url):
                    continue

                article = extraire_article(url, config, resume_prefill=resume)
                if article is None:
                    continue
                article.update({
                    "date_publication": date_pub, "annee": annee, "mois": mois,
                    "jour": jour, "methode_collecte": "rss"
                })
                sauvegarder_article(source_id, article)
                nouveaux += 1
                log.info(f"  ✓ {titre[:65]} | {date_pub}")
                time.sleep(1.5)

                if mode_test and nouveaux >= 5:
                    stop = True; break

            if stop:
                break
            time.sleep(1.0)

    return nouveaux, nouveaux > 0 or True  # RSS disponible même si 0 résultats filtrés


# ─────────────────────────────────────────────────────────────────
# MÉTHODE 3 — HTML FALLBACK
# ─────────────────────────────────────────────────────────────────

def collecter_via_html(source_id, config, date_limite, mode_test):
    log.info("  → Fallback HTML")
    nouveaux = 0

    for liste_path in config["listes_html"]:
        page = 1
        while True:
            url_liste = config["base_url"] + liste_path + (f"page/{page}/" if page > 1 else "")
            r = get(url_liste)
            if r is None:
                break

            soup = BeautifulSoup(r.text, "html.parser")
            urls_page = []
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if not href.startswith("http"):
                    href = config["base_url"] + href if href.startswith("/") else None
                if not href or not href.startswith(config["base_url"]):
                    continue
                chemin = href.replace(config["base_url"], "")
                if any(chemin.startswith(p) for p in config["prefixes"]):
                    if len(chemin.strip("/")) > 8 and href not in urls_page:
                        urls_page.append(href)

            if not urls_page:
                break

            stop = False
            for url in urls_page:
                if url_existe(url):
                    continue
                article = extraire_article(url, config)
                if article is None:
                    continue
                if not est_pertinent(article["titre"] or "", article["resume"] or "", config["filtrer"]):
                    continue
                if date_limite and article["date_publication"]:
                    dt = datetime.strptime(article["date_publication"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                    if dt < date_limite:
                        stop = True; break
                sauvegarder_article(source_id, article)
                nouveaux += 1
                log.info(f"  ✓ {(article['titre'] or '')[:65]} | {article['date_publication']}")
                time.sleep(1.5)

            if stop or mode_test:
                break
            page += 1
            time.sleep(1.0)

    return nouveaux


# ─────────────────────────────────────────────────────────────────
# SCRAPER PRINCIPAL
# ─────────────────────────────────────────────────────────────────

def scraper_source(source_key, date_depuis=None, mode_test=False):
    config = SOURCES[source_key]
    source_id = SOURCE_IDS[source_key]

    date_limite = None
    if date_depuis:
        date_limite = datetime.strptime(date_depuis, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        log.info(f"Filtre actif : articles depuis le {date_depuis}")

    log.info(f"\n── {config['nom'].upper()} ──")

    n, ok = collecter_via_api(source_id, config, date_limite, mode_test)
    if ok:
        log.info(f"→ {source_key} [API WP] : {n} article(s)")
        return n

    log.info("  API indisponible → RSS")
    n, ok = collecter_via_rss(source_id, config, date_limite, mode_test)
    log.info(f"→ {source_key} [RSS] : {n} article(s)")
    return n


def scraper(sources=None, date_depuis=None, mode_test=False):
    cles = list(SOURCES.keys()) if sources is None else sources
    total = 0
    for key in cles:
        n = scraper_source(key, date_depuis, mode_test)
        total += n
    log.info(f"\n{'='*55}")
    log.info(f"Collecte terminée — {total} nouvel(s) article(s) au total")


# ─────────────────────────────────────────────────────────────────
# API DE REQUÊTE PAR DATE
# ─────────────────────────────────────────────────────────────────

def requete_par_date(source_key, date_debut=None, date_fin=None, annee=None, mois=None, limit=50):
    db_path = SOURCES[source_key]["db"]
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cond, params = [], []
    if date_debut: cond.append("date_publication >= ?"); params.append(date_debut)
    if date_fin:   cond.append("date_publication <= ?"); params.append(date_fin + " 23:59:59")
    if annee:      cond.append("annee = ?");            params.append(annee)
    if mois:       cond.append("mois = ?");             params.append(mois)
    where = ("WHERE " + " AND ".join(cond)) if cond else ""
    rows = conn.execute(
        f"SELECT * FROM articles {where} ORDER BY date_publication DESC LIMIT ?",
        params + [limit]
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def stats_db(source_key):
    db_path = SOURCES[source_key]["db"]
    from pathlib import Path
    if not Path(db_path).exists():
        print(f"  {source_key} : base non créée")
        return
    conn = sqlite3.connect(db_path)
    total    = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
    par_an   = dict(conn.execute("SELECT annee, COUNT(*) FROM articles GROUP BY annee ORDER BY annee").fetchall())
    recent   = conn.execute("SELECT MAX(date_publication) FROM articles").fetchone()[0]
    methodes = dict(conn.execute("SELECT methode_collecte, COUNT(*) FROM articles GROUP BY methode_collecte").fetchall())
    conn.close()
    print(f"  [{source_key}] {SOURCES[source_key]['nom']}")
    print(f"    Total : {total} | Par année : {par_an} | Méthodes : {methodes} | Récent : {recent}")


# ─────────────────────────────────────────────────────────────────
# POINT D'ENTRÉE CLI
# ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Scraper WP générique — Banque du Canada, CBK Kenya, Bank of Ghana")
    ap.add_argument("--source",  nargs="+", choices=list(SOURCES.keys()) + ["all"], default=["all"])
    ap.add_argument("--depuis",  metavar="YYYY-MM-DD")
    ap.add_argument("--test",    action="store_true")
    ap.add_argument("--stats",   action="store_true")
    args = ap.parse_args()

    if args.stats:
        print(f"\n{'─'*50}")
        for key in SOURCES:
            stats_db(key)
        print(f"{'─'*50}")
    else:
        sources = list(SOURCES.keys()) if "all" in args.source else args.source
        scraper(sources=sources, date_depuis=args.depuis, mode_test=args.test)
