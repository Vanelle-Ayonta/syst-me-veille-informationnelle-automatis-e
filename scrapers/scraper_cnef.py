"""
Scraper — CNEF Cameroun (cnefcameroun.cm)
==========================================
Collecte les publications et actualités du CNEF et les stocke en SQLite.

STRUCTURE DU SITE
─────────────────
Site WordPress (WordPress Download Manager 3.x) en français.

Sections pertinentes pour la veille inclusion financière :
  - Nouvelles          : /actualite/
  - Rapports           : /rapport/
  - Notes thématiques  : /notes/
  - Bulletins          : /bulletin-du-cnef/
  - Communiqués        : /communiquer/

Stratégie :
  1. API REST WordPress /wp-json/wp/v2/posts?page=N (priorité)
  2. Fallback : scraping HTML /page/N/

Format de date : ISO 8601 (meta article:published_time — WordPress standard)

NOTE RÉSEAU : Exécuter depuis poste DIIF (bloqué depuis serveurs distants).

USAGE
─────
    python scraper_cnef.py                       # collecte complète
    python scraper_cnef.py --depuis 2023-01-01
    python scraper_cnef.py --type actualite
    python scraper_cnef.py --test
    python scraper_cnef.py --stats
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
    "CNEF Cameroun",
    "https://cnefcameroun.cm", "fr", "web"
)

BASE_URL = "https://cnefcameroun.cm"
DB_PATH  = "cnef_cameroun.db"
DELAI    = 1.5

SOURCES = {
    # Seule la section actualités est retenue pour le CNEF Cameroun
    "actualite": {
        "liste":    "/actualite/",
        "api_wp":   "/wp-json/wp/v2/posts?per_page=10&page={page}&_fields=id,title,date,link,excerpt",
        "prefixes": ["/actualite/"],
        "type":     "actualite",
    },
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    "Referer": "https://cnefcameroun.cm/",
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
log = logging.getLogger(__name__)


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


def get(url, json_mode=False, timeout=12):
    h = {**HEADERS, "Accept": "application/json"} if json_mode else HEADERS
    try:
        r = requests.get(url, headers=h, timeout=timeout)
        r.raise_for_status()
        return r
    except requests.RequestException as e:
        log.warning(f"Erreur [{url[-65:]}] : {e}")
        return None


def extraire_article(url, type_contenu, resume_prefill=None):
    r = get(url)
    if r is None:
        return None
    soup = BeautifulSoup(r.text, "html.parser")

    titre = None
    og = soup.find("meta", property="og:title")
    if og:
        titre = og.get("content", "").replace(" - Cnef", "").replace(" – Cnef", "").strip()
    if not titre:
        h1 = soup.find("h1")
        titre = h1.get_text(strip=True) if h1 else None

    date_pub = annee = mois = jour = None
    meta_date = soup.find("meta", property="article:published_time")
    if meta_date:
        date_pub, annee, mois, jour = parser_date_iso(meta_date.get("content", ""))
    if not date_pub:
        t = soup.find("time", attrs={"datetime": True})
        if t:
            date_pub, annee, mois, jour = parser_date_iso(t["datetime"])

    resume = resume_prefill
    if not resume:
        m = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", property="og:description")
        if m:
            resume = m.get("content", "").strip()

    contenu = ""
    corps = (soup.find("div", class_=re.compile(r"entry-content|post-content"))
             or soup.find("article") or soup.find("main"))
    if corps:
        for tag in corps.find_all(["script", "style", "nav", "aside", "form", "header", "footer"]):
            tag.decompose()
        contenu = corps.get_text(separator="\n", strip=True)[:8000]

    return {
        "url": url, "titre": titre,
        "date_publication": date_pub, "annee": annee, "mois": mois, "jour": jour,
        "type_contenu": type_contenu, "langue": "fr",
        "resume": resume, "contenu": contenu,
        "methode_collecte": "html",
        "date_scraping": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
    }


def collecter_via_api(type_nom, config, date_limite, mode_test):
    log.info("  → Tentative API REST WordPress")
    nouveaux, page = 0, 1
    while True:
        r = get(BASE_URL + config["api_wp"].format(page=page), json_mode=True, timeout=8)
        if r is None:
            return nouveaux, False
        try:
            items = r.json()
        except Exception:
            return nouveaux, False
        if not items or not isinstance(items, list):
            log.info(f"  Fin des résultats API à la page {page}")
            break
        # Si moins d'items que demandé → dernière page
        if len(items) < 10:
            log.info(f"  Dernière page API ({len(items)} items)")

        stop = False
        for item in items:
            url = item.get("link", "")
            titre = BeautifulSoup(item.get("title", {}).get("rendered", ""), "html.parser").get_text(strip=True)
            date_iso = item.get("date_gmt", item.get("date", ""))
            resume = BeautifulSoup(item.get("excerpt", {}).get("rendered", ""), "html.parser").get_text(strip=True)[:500]
            date_pub, annee, mois, jour = parser_date_iso(date_iso)

            if date_limite and date_pub:
                dt = datetime.strptime(date_pub, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                if dt < date_limite:
                    log.info(f"  ↩ Trop ancien ({date_pub}) — arrêt")
                    stop = True; break

            if not url or url_existe(url):
                continue

            article = extraire_article(url, config["type"], resume_prefill=resume)
            if article is None:
                continue
            article.update({"date_publication": date_pub, "annee": annee, "mois": mois, "jour": jour, "methode_collecte": "api_wp"})
            sauvegarder_article(SOURCE_ID, article)
            nouveaux += 1
            log.info(f"  ✓ {titre[:65]} | {date_pub}")
            time.sleep(DELAI)

        if stop or mode_test or len(items) < 10:
            break
        page += 1
        time.sleep(DELAI)
    return nouveaux, True


def collecter_via_html(type_nom, config, date_limite, mode_test):
    log.info("  → Fallback scraping HTML")
    nouveaux, page = 0, 1
    while True:
        url_liste = BASE_URL + config["liste"] + (f"page/{page}/" if page > 1 else "")
        log.info(f"  Page {page} : {url_liste}")
        r = get(url_liste)
        if r is None:
            break
        soup = BeautifulSoup(r.text, "html.parser")
        urls_page = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if not href.startswith("http"):
                href = BASE_URL + href if href.startswith("/") else None
            if not href:
                continue
            chemin = href.replace(BASE_URL, "")
            if any(chemin.startswith(p) for p in config["prefixes"]) and len(chemin.strip("/")) > 5:
                if href not in urls_page:
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
                dt = datetime.strptime(article["date_publication"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                if dt < date_limite:
                    stop = True; break
            sauvegarder_article(SOURCE_ID, article)
            nouveaux += 1
            log.info(f"  ✓ {(article['titre'] or '')[:65]} | {article['date_publication']}")
            time.sleep(DELAI)
        if stop or mode_test:
            break
        page += 1
        time.sleep(DELAI)
    return nouveaux


def scraper(date_depuis=None, types=None, mode_test=False):
    date_limite = None
    if date_depuis:
        date_limite = datetime.strptime(date_depuis, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        log.info(f"Filtre actif : articles depuis le {date_depuis}")
    sources_actives = {k: v for k, v in SOURCES.items() if types is None or k in types}
    total = 0
    for type_nom, config in sources_actives.items():
        log.info(f"\n── {type_nom.upper()} ──")
        n, ok = collecter_via_api(type_nom, config, date_limite, mode_test)
        if not ok:
            log.warning("  API indisponible — collecte ignorée pour cette session.")
            log.warning("  Conseil : réessayer ultérieurement (l'API est généralement stable).")
        total += n
        log.info(f"→ {type_nom} : {n} article(s)")

    log.info(f"\n{'='*55}")
    log.info(f"Collecte terminée — {total} nouvel(s) article(s)")


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
    rows = conn.execute(f"SELECT * FROM articles {where} ORDER BY date_publication DESC LIMIT ?", params + [limit]).fetchall()
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


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Scraper CNEF Cameroun → SQLite (DIIF/BEAC)")
    ap.add_argument("--depuis",  metavar="YYYY-MM-DD")
    ap.add_argument("--type",    nargs="+", choices=["actualite"])
    ap.add_argument("--test",    action="store_true")
    ap.add_argument("--db",      default=DB_PATH)
    ap.add_argument("--stats",   action="store_true")
    args = ap.parse_args()
    if args.stats:
        s = stats_db(args.db)
        print(f"\n{'─'*40}\nBase : {args.db}\nTotal : {s['total']}\nPar type : {s['par_type']}\nPar année : {s['par_annee']}\nPlus récent : {s['plus_recent']}\n{'─'*40}")
    else:
        scraper(date_depuis=args.depuis, types=args.type, mode_test=args.test)
