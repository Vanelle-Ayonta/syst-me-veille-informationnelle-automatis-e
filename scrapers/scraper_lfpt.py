"""
Scraper — La Finance pour Tous (lafinancepourtous.com)
=======================================================
Collecte les actualités sur l'éducation et l'inclusion financière.

STRUCTURE DU SITE
─────────────────
Site WordPress en français. Section cible : /actualites/
URLs articles : /YYYY/MM/DD/titre-article/

Stratégie :
  1. RSS /feed/ (WordPress standard)
  2. Fallback : API REST WP /wp-json/wp/v2/posts

Format de date : RFC 2822 (RSS) ou ISO 8601 (meta article:published_time)

NOTE RÉSEAU : Exécuter depuis poste DIIF.

USAGE
─────
    python scraper_lfpt.py                       # collecte complète
    python scraper_lfpt.py --depuis 2023-01-01
    python scraper_lfpt.py --test
    python scraper_lfpt.py --stats
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
    "La Finance pour Tous", "https://www.lafinancepourtous.com", "fr", "rss"
)

BASE_URL = "https://www.lafinancepourtous.com"
DB_PATH  = "lafinancepourtous.db"
DELAI    = 1.5

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9",
    "Referer": "https://www.lafinancepourtous.com/",
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


def parser_date_url(url):
    """Extrait la date depuis l'URL WordPress /YYYY/MM/DD/titre/"""
    m = re.search(r'/(\d{4})/(\d{2})/(\d{2})/', url)
    if m:
        a, mo, j = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return f"{a:04d}-{mo:02d}-{j:02d} 00:00:00", a, mo, j
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


def is_article(url):
    """Vérifie que l'URL est bien un article (pas une page de navigation)."""
    if not url.startswith(BASE_URL):
        return False
    chemin = url.replace(BASE_URL, "")
    # Articles WP avec date dans l'URL : /2024/03/13/titre/
    if re.search(r'/\d{4}/\d{2}/\d{2}/', chemin):
        return True
    return False


def extraire_article(url, resume_prefill=None):
    r = get(url)
    if r is None:
        return None
    soup = BeautifulSoup(r.text, "html.parser")

    # Titre
    titre = None
    og = soup.find("meta", property="og:title")
    if og:
        titre = og.get("content", "").replace(" - La finance pour tous", "").strip()
    if not titre:
        h1 = soup.find("h1")
        titre = h1.get_text(strip=True) if h1 else None

    # Date — plusieurs sources
    date_pub = annee = mois = jour = None
    meta_date = soup.find("meta", property="article:published_time")
    if meta_date:
        date_pub, annee, mois, jour = parser_date_iso(meta_date.get("content", ""))
    if not date_pub:
        t = soup.find("time", attrs={"datetime": True})
        if t:
            date_pub, annee, mois, jour = parser_date_iso(t["datetime"])
    if not date_pub:
        date_pub, annee, mois, jour = parser_date_url(url)

    # Catégorie
    categorie = None
    cat = soup.find("a", rel="category tag")
    if cat:
        categorie = cat.get_text(strip=True)

    # Résumé
    resume = resume_prefill
    if not resume:
        m = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", property="og:description")
        if m:
            resume = m.get("content", "").strip()

    # Contenu
    contenu = ""
    corps = (soup.find("div", class_=re.compile(r"entry-content|post-content|article-content"))
             or soup.find("article") or soup.find("main"))
    if corps:
        for tag in corps.find_all(["script", "style", "nav", "aside", "form", "header", "footer"]):
            tag.decompose()
        contenu = corps.get_text(separator="\n", strip=True)[:8000]

    return {
        "url": url, "titre": titre,
        "date_publication": date_pub, "annee": annee, "mois": mois, "jour": jour,
        "categorie": categorie, "langue": "fr",
        "resume": resume, "contenu": contenu,
        "methode_collecte": "html",
        "date_scraping": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
    }


# ─── MÉTHODE 1 : RSS ─────────────────────────────────────────────

def collecter_via_rss(date_limite, mode_test):
    log.info("  → Flux RSS")
    nouveaux = 0

    # LFPT expose plusieurs flux RSS paginés
    for page in range(1, 50):
        url_rss = f"{BASE_URL}/feed/" if page == 1 else f"{BASE_URL}/feed/?paged={page}"
        r = get(url_rss)
        if r is None:
            return nouveaux, False

        soup = BeautifulSoup(r.content, "xml")
        items = soup.find_all("item")
        if not items:
            log.info(f"  Fin du flux à la page {page}")
            break

        log.info(f"  Page {page} : {len(items)} item(s)")
        stop = False

        for item in items:
            url = getattr(item.find("link"), "text", "").strip()
            titre = getattr(item.find("title"), "text", "").strip()
            date_rss = getattr(item.find("pubDate"), "text", "").strip()
            resume = BeautifulSoup(
                getattr(item.find("description"), "text", "") or "", "html.parser"
            ).get_text(strip=True)[:500]
            categorie = getattr(item.find("category"), "text", "").strip()

            date_pub, annee, mois, jour = parser_date_rss(date_rss)
            if not date_pub:
                date_pub, annee, mois, jour = parser_date_url(url)

            if date_limite and date_pub:
                dt = datetime.strptime(date_pub, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                if dt < date_limite:
                    log.info(f"  ↩ Trop ancien ({date_pub}) — arrêt")
                    stop = True
                    break

            if not url or not is_article(url) or url_existe(url):
                continue

            article = extraire_article(url, resume_prefill=resume)
            if article is None:
                continue
            article.update({
                "date_publication": date_pub, "annee": annee, "mois": mois, "jour": jour,
                "categorie": categorie or article.get("categorie"),
                "methode_collecte": "rss"
            })
            sauvegarder_article(SOURCE_ID, article)
            nouveaux += 1
            log.info(f"  ✓ {titre[:65]} | {date_pub}")
            time.sleep(DELAI)

            if mode_test and nouveaux >= 10:
                stop = True
                break

        if stop:
            break
        time.sleep(DELAI)

    return nouveaux, True


# ─── MÉTHODE 2 : API REST WP (fallback) ──────────────────────────

def collecter_via_api(date_limite, mode_test):
    log.info("  → Fallback API REST WordPress")
    nouveaux, page = 0, 1

    while True:
        url_api = f"{BASE_URL}/wp-json/wp/v2/posts?per_page=10&page={page}&_fields=id,title,date,link,excerpt,categories"
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


# ─── SCRAPER PRINCIPAL ────────────────────────────────────────────

def scraper(date_depuis=None, mode_test=False):
    date_limite = None
    if date_depuis:
        date_limite = datetime.strptime(date_depuis, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        log.info(f"Filtre actif : articles depuis le {date_depuis}")

    log.info("\n── ACTUALITES LA FINANCE POUR TOUS ──")
    n, ok = collecter_via_rss(date_limite, mode_test)
    if not ok:
        log.info("  RSS indisponible → API REST WP")
        n, ok = collecter_via_api(date_limite, mode_test)

    log.info(f"\n{'='*55}")
    log.info(f"Collecte terminée — {n} nouvel(s) article(s)")


def requete_par_date(db_path=DB_PATH, date_debut=None, date_fin=None,
                     categorie=None, annee=None, mois=None, limit=50):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cond, params = [], []
    if date_debut:  cond.append("date_publication >= ?"); params.append(date_debut)
    if date_fin:    cond.append("date_publication <= ?"); params.append(date_fin + " 23:59:59")
    if categorie:   cond.append("categorie LIKE ?");     params.append(f"%{categorie}%")
    if annee:       cond.append("annee = ?");            params.append(annee)
    if mois:        cond.append("mois = ?");             params.append(mois)
    where = ("WHERE " + " AND ".join(cond)) if cond else ""
    rows = conn.execute(f"SELECT * FROM articles {where} ORDER BY date_publication DESC LIMIT ?", params + [limit]).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def stats_db(db_path=DB_PATH):
    conn = sqlite3.connect(db_path)
    s = {
        "total":       conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0],
        "par_annee":   dict(conn.execute("SELECT annee, COUNT(*) FROM articles GROUP BY annee ORDER BY annee").fetchall()),
        "par_categorie": dict(conn.execute("SELECT categorie, COUNT(*) FROM articles GROUP BY categorie ORDER BY 2 DESC LIMIT 10").fetchall()),
        "plus_recent": conn.execute("SELECT MAX(date_publication) FROM articles").fetchone()[0],
        "plus_ancien": conn.execute("SELECT MIN(date_publication) FROM articles").fetchone()[0],
    }
    conn.close()
    return s


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Scraper La Finance pour Tous → SQLite (DIIF/BEAC)")
    ap.add_argument("--depuis", metavar="YYYY-MM-DD")
    ap.add_argument("--test",   action="store_true")
    ap.add_argument("--db",     default=DB_PATH)
    ap.add_argument("--stats",  action="store_true")
    args = ap.parse_args()

    if args.stats:
        s = stats_db(args.db)
        print(f"\n{'─'*40}\nBase : {args.db}\nTotal : {s['total']}\nPar année : {s['par_annee']}\nPar catégorie : {s['par_categorie']}\nPlus récent : {s['plus_recent']}\n{'─'*40}")
    else:
        scraper(date_depuis=args.depuis, mode_test=args.test)
