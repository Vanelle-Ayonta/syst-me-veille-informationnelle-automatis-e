"""
Scraper — GIMAC (gimac-afr.com)
================================
Collecte les actualités du GIMAC et les stocke en SQLite.

STRUCTURE DU SITE
─────────────────
Site WordPress (+ Slider Revolution) en français/anglais.
Section cible : /actualites/

Stratégie :
  1. API REST WordPress /wp-json/wp/v2/posts?page=N
  2. Fallback : RSS /feed/

Format de date : ISO 8601 (meta article:published_time)
Langue : fr (version anglaise disponible sur /en/)

NOTE RÉSEAU : Exécuter depuis poste DIIF.

USAGE
─────
    python scraper_gimac.py                       # collecte complète
    python scraper_gimac.py --depuis 2023-01-01
    python scraper_gimac.py --test
    python scraper_gimac.py --stats
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
SOURCE_ID = get_or_create_source(
    "GIMAC", "https://gimac-afr.com", "fr", "web"
)
BASE_URL = "https://gimac-afr.com"
DB_PATH  = "gimac.db"
DELAI    = 1.5

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    "Referer": "https://gimac-afr.com/",
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


def parser_date_rss(rfc2822):
    if not rfc2822:
        return None, None, None, None
    try:
        dt = parsedate_to_datetime(rfc2822).astimezone(timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M:%S"), dt.year, dt.month, dt.day
    except Exception:
        return None, None, None, None


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


def extraire_article(url, resume_prefill=None):
    r = get(url)
    if r is None:
        return None
    soup = BeautifulSoup(r.text, "html.parser")

    titre = None
    og = soup.find("meta", property="og:title")
    if og:
        titre = og.get("content", "").replace(" – GIMAC", "").replace(" - GIMAC", "").strip()
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
        "type_contenu": "actualite", "langue": "fr",
        "resume": resume, "contenu": contenu,
        "methode_collecte": "html",
        "date_scraping": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
    }


# ─── MÉTHODE 1 : API REST WordPress ──────────────────────────────

def collecter_via_api(date_limite, mode_test):
    log.info("  → Tentative API REST WordPress")
    nouveaux, page = 0, 1

    while True:
        url_api = f"{BASE_URL}/wp-json/wp/v2/posts?per_page=10&page={page}&_fields=id,title,date,link,excerpt"
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

            article = extraire_article(url, resume_prefill=resume)
            if article is None:
                continue
            article.update({"date_publication": date_pub, "annee": annee, "mois": mois,
                             "jour": jour, "methode_collecte": "api_wp"})
            sauvegarder_article(SOURCE_ID, article)
            nouveaux += 1
            log.info(f"  ✓ {titre[:65]} | {date_pub}")
            time.sleep(DELAI)

        if stop or mode_test or len(items) < 10:
            break
        page += 1
        time.sleep(DELAI)

    return nouveaux, True


# ─── MÉTHODE 2 : RSS ─────────────────────────────────────────────

def collecter_via_rss(date_limite, mode_test):
    log.info("  → Fallback RSS")
    nouveaux = 0
    r = get(f"{BASE_URL}/feed/")
    if r is None:
        return nouveaux, False

    soup = BeautifulSoup(r.content, "xml")
    items = soup.find_all("item")
    if not items:
        return nouveaux, False

    log.info(f"  {len(items)} item(s) dans le flux")
    for item in items:
        url = getattr(item.find("link"), "text", "").strip()
        titre = getattr(item.find("title"), "text", "").strip()
        date_rss = getattr(item.find("pubDate"), "text", "").strip()
        resume = BeautifulSoup(getattr(item.find("description"), "text", "") or "", "html.parser").get_text(strip=True)[:500]
        date_pub, annee, mois, jour = parser_date_rss(date_rss)

        if date_limite and date_pub:
            dt = datetime.strptime(date_pub, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            if dt < date_limite:
                break

        if not url or url_existe(url):
            continue

        article = extraire_article(url, resume_prefill=resume)
        if article is None:
            continue
        article.update({"date_publication": date_pub, "annee": annee, "mois": mois,
                         "jour": jour, "methode_collecte": "rss"})
        sauvegarder_article(SOURCE_ID, article)
        nouveaux += 1
        log.info(f"  ✓ {titre[:65]} | {date_pub}")
        time.sleep(DELAI)

        if mode_test and nouveaux >= 5:
            break

    return nouveaux, True


# ─── SCRAPER PRINCIPAL ────────────────────────────────────────────

def scraper(date_depuis=None, mode_test=False):
    date_limite = None
    if date_depuis:
        date_limite = datetime.strptime(date_depuis, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        log.info(f"Filtre actif : articles depuis le {date_depuis}")

    log.info("\n── ACTUALITES GIMAC ──")
    n, ok = collecter_via_api(date_limite, mode_test)
    if not ok:
        log.info("  API indisponible → RSS")
        n, ok = collecter_via_rss(date_limite, mode_test)
        if not ok:
            log.warning("  RSS également indisponible — vérifier la connexion réseau")

    log.info(f"\n{'='*55}")
    log.info(f"Collecte terminée — {n} nouvel(s) article(s)")


def requete_par_date(db_path=DB_PATH, date_debut=None, date_fin=None,
                     annee=None, mois=None, limit=50):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cond, params = [], []
    if date_debut: cond.append("date_publication >= ?"); params.append(date_debut)
    if date_fin:   cond.append("date_publication <= ?"); params.append(date_fin + " 23:59:59")
    if annee:      cond.append("annee = ?");            params.append(annee)
    if mois:       cond.append("mois = ?");             params.append(mois)
    where = ("WHERE " + " AND ".join(cond)) if cond else ""
    rows = conn.execute(f"SELECT * FROM articles {where} ORDER BY date_publication DESC LIMIT ?", params + [limit]).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def stats_db(db_path=DB_PATH):
    conn = sqlite3.connect(db_path)
    s = {
        "total":       conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0],
        "par_annee":   dict(conn.execute("SELECT annee, COUNT(*) FROM articles GROUP BY annee ORDER BY annee").fetchall()),
        "plus_recent": conn.execute("SELECT MAX(date_publication) FROM articles").fetchone()[0],
        "plus_ancien": conn.execute("SELECT MIN(date_publication) FROM articles").fetchone()[0],
    }
    conn.close()
    return s


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Scraper GIMAC → SQLite (DIIF/BEAC)")
    ap.add_argument("--depuis", metavar="YYYY-MM-DD")
    ap.add_argument("--test",   action="store_true")
    ap.add_argument("--db",     default=DB_PATH)
    ap.add_argument("--stats",  action="store_true")
    args = ap.parse_args()

    if args.stats:
        s = stats_db(args.db)
        print(f"\n{'─'*40}\nBase : {args.db}\nTotal : {s['total']}\nPar année : {s['par_annee']}\nPlus récent : {s['plus_recent']}\n{'─'*40}")
    else:
        scraper(date_depuis=args.depuis, mode_test=args.test)
