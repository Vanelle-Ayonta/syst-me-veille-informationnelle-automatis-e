"""
Scraper — BRI / BIS (bis.org)
==============================
Collecte les publications de la Banque des Règlements Internationaux
liées à l'inclusion financière, fintech et paiements digitaux.

STRUCTURE DU SITE
─────────────────
Le site BRI n'utilise pas WordPress. Il expose :
  - Des flux RSS par type de publication (working papers, BIS Papers, etc.)
  - Des pages de liste paginées (/list/research/index.htm?m=N&n=20)
  - Des pages HTML légères par publication (/publ/work{N}.htm)

Stratégie :
  1. RSS en priorité (flux officiels, dates structurées)
  2. Fallback : pages de liste HTML

Flux RSS disponibles :
  - Working Papers     : /rss/list/work.rss
  - BIS Papers         : /rss/list/bppdf.rss
  - BIS Bulletins      : /rss/list/bisbull.rss
  - FSI Papers         : /rss/list/fsi_papers.rss
  - Quarterly Review   : /rss/list/qtrpdf.rss

Filtre thématique : seules les publications mentionnant des mots-clés
liés à l'inclusion financière sont retenues.

Format de date : RFC 2822 dans le RSS | texte ('12 December 2024') dans HTML

NOTE RÉSEAU : Exécuter depuis poste DIIF.

USAGE
─────
    python scraper_bis.py                       # collecte complète
    python scraper_bis.py --depuis 2023-01-01
    python scraper_bis.py --type working_papers
    python scraper_bis.py --test
    python scraper_bis.py --stats
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

SOURCE_ID = get_or_create_source("BRI / BIS", "https://www.bis.org", "en", "rss")

BASE_URL = "https://www.bis.org"
DB_PATH  = "bis.db"
DELAI    = 1.5

# Mots-clés inclusion financière pour le filtre thématique
MOTS_CLES_IF = [
    "financial inclusion", "inclusion financière", "fintech", "mobile money",
    "digital payment", "unbanked", "microfinance", "remittance",
    "financial access", "digital finance", "cbdc", "central bank digital",
    "payment system", "financial literacy", "financial education",
    "developing econom", "emerging market", "africa", "sub-saharan",
    "cemac", "fast payment", "interoperability",
    "open finance", "stablecoin", "crypto", "defi",
    "cross-border payment", "financial health", "financial wellbeing",
    "instant payment", "retail payment", "digital currency"
]

SOURCES = {
    # Un seul flux RSS couvre toutes les publications de recherche BRI
    "research": {
        "rss":     "/doclist/bis_fsi_publs.rss",
        "liste":   "/publ/research/index.htm",
        "prefixes":["/publ/work", "/publ/bppdf/", "/publ/bisbull",
                    "/publ/fsi", "/publ/qtrpdf/"],
        "type":    "research",
    },
    # Communiqués de presse
    "press": {
        "rss":     "/doclist/all_pressrels.rss",
        "liste":   "/press/index.htm",
        "prefixes":["/press/p"],
        "type":    "press_release",
    },
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.bis.org/",
}

MOIS_EN = {
    "january":1,"february":2,"march":3,"april":4,"may":5,"june":6,
    "july":7,"august":8,"september":9,"october":10,"november":11,"december":12,
    "jan":1,"feb":2,"mar":3,"apr":4,"jun":6,"jul":7,"aug":8,
    "sep":9,"oct":10,"nov":11,"dec":12,
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
log = logging.getLogger(__name__)


# ─── UTILITAIRES ──────────────────────────────────────────────────

def parser_date_rss(rfc2822):
    if not rfc2822:
        return None, None, None, None
    try:
        dt = parsedate_to_datetime(rfc2822).astimezone(timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M:%S"), dt.year, dt.month, dt.day
    except Exception:
        return None, None, None, None


def parser_date_texte(texte):
    """Parse '12 December 2024' ou '2024-12-12'"""
    if not texte:
        return None, None, None, None
    texte = texte.strip()

    m = re.search(r'(\d{4})-(\d{2})-(\d{2})', texte)
    if m:
        a, mo, j = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return f"{a:04d}-{mo:02d}-{j:02d} 00:00:00", a, mo, j

    m = re.search(r'(\d{1,2})\s+([a-z]+)\s+(\d{4})', texte.lower())
    if m:
        j = int(m.group(1))
        mo = MOIS_EN.get(m.group(2)[:9])
        a = int(m.group(3))
        if mo:
            return f"{a:04d}-{mo:02d}-{j:02d} 00:00:00", a, mo, j

    return None, None, None, None


def est_pertinent(titre, resume):
    texte = f"{titre} {resume}".lower()
    return any(mot in texte for mot in MOTS_CLES_IF)


def get(url, timeout=12, retries=2):
    for tentative in range(retries + 1):
        try:
            r = requests.get(url, headers=HEADERS, timeout=timeout)
            r.raise_for_status()
            return r
        except requests.RequestException as e:
            if tentative < retries:
                log.warning(f"Erreur [{url[-60:]}] retry {tentative+1}/{retries} : {e}")
                time.sleep(3)
            else:
                log.warning(f"Erreur [{url[-60:]}] : {e}")
                return None


def extraire_article(url, type_contenu):
    r = get(url)
    if r is None:
        return None
    soup = BeautifulSoup(r.text, "html.parser")

    # Titre
    titre = None
    og = soup.find("meta", property="og:title")
    if og:
        titre = og.get("content", "").replace(" - BIS", "").strip()
    if not titre:
        h1 = soup.find("h1")
        titre = h1.get_text(strip=True) if h1 else None

    # Date
    date_pub = annee = mois = jour = None
    t = soup.find("time")
    if t:
        date_pub, annee, mois, jour = parser_date_texte(t.get("datetime", "") or t.get_text(strip=True))
    if not date_pub:
        m = re.search(
            r'\b\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}\b',
            soup.get_text(), re.IGNORECASE
        )
        if m:
            date_pub, annee, mois, jour = parser_date_texte(m.group())

    # Résumé / abstract
    resume = None
    meta = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", property="og:description")
    if meta:
        resume = meta.get("content", "").strip()
    if not resume:
        # BRI place souvent l'abstract dans un div spécifique
        abstract = soup.find("div", class_=re.compile(r"abstract|summary|content"))
        if abstract:
            resume = abstract.get_text(strip=True)[:500]

    # Contenu
    contenu = ""
    corps = soup.find("div", class_=re.compile(r"content|main|article")) or soup.find("main")
    if corps:
        for tag in corps.find_all(["script", "style", "nav", "aside", "form", "header", "footer"]):
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


# ─── MÉTHODE 1 : RSS ──────────────────────────────────────────────

def collecter_via_rss(type_nom, config, date_limite, mode_test):
    log.info("  → Flux RSS")
    nouveaux = 0
    url_rss = BASE_URL + config["rss"]
    r = get(url_rss)
    if r is None:
        return nouveaux, False

    soup = BeautifulSoup(r.content, "xml")
    items = soup.find_all("item")
    if not items:
        return nouveaux, False

    log.info(f"  {len(items)} item(s) dans le flux")
    stop = False

    for item in items:
        url_raw = getattr(item.find("link"), "text", "") or ""
        url = url_raw.strip()
        if not url.startswith("http"):
            url = BASE_URL + url

        titre   = getattr(item.find("title"), "text", "").strip()
        desc    = BeautifulSoup(getattr(item.find("description"), "text", "") or "", "html.parser").get_text(strip=True)[:500]
        # BRI utilise dc:date ou pubDate selon le flux
        date_rss = ""
        for tag in ["pubDate", "dc:date", "date", "updated", "published"]:
            el = item.find(tag)
            if el and el.text.strip():
                date_rss = el.text.strip()
                break

        # Essayer d'abord RFC 2822 (pubDate), puis ISO 8601 (dc:date)
        date_pub, annee, mois, jour = parser_date_rss(date_rss)
        if not date_pub:
            date_pub, annee, mois, jour = parser_date_texte(date_rss)

        # Filtre thématique — ne garder que publications IF
        if not est_pertinent(titre, desc):
            continue

        if date_limite and date_pub:
            dt = datetime.strptime(date_pub, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            if dt < date_limite:
                log.info(f"  ↩ Trop ancien ({date_pub}) — arrêt")
                stop = True
                break

        if not url or url_existe(url):
            continue

        article = extraire_article(url, config["type"])
        if article is None:
            continue

        article["titre"] = article["titre"] or titre
        if date_pub:
            article["date_publication"] = date_pub
            article["annee"] = annee
            article["mois"] = mois
            article["jour"] = jour
        article["resume"] = article["resume"] or desc
        article["methode_collecte"] = "rss"

        sauvegarder_article(SOURCE_ID, article)
        nouveaux += 1
        log.info(f"  ✓ {titre[:65]} | {date_pub}")
        time.sleep(DELAI)

        if mode_test and nouveaux >= 5:
            break

    return nouveaux, not stop


# ─── MÉTHODE 2 : LISTE HTML ───────────────────────────────────────

def collecter_via_html(type_nom, config, date_limite, mode_test):
    log.info("  → Fallback liste HTML")
    nouveaux = 0
    offset = 0
    per_page = 20

    while True:
        url_liste = BASE_URL + config["liste"] + f"?m={offset}&n={per_page}"
        log.info(f"  Offset {offset} : {url_liste}")
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
            if any(chemin.startswith(p) for p in config["prefixes"]) and href not in urls_page:
                urls_page.append(href)

        if not urls_page:
            log.info("  Fin de liste")
            break

        stop = False
        for url in urls_page:
            if url_existe(url):
                continue
            article = extraire_article(url, config["type"])
            if article is None:
                continue
            if not est_pertinent(article["titre"] or "", article["resume"] or ""):
                continue
            if date_limite and article["date_publication"]:
                dt = datetime.strptime(article["date_publication"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                if dt < date_limite:
                    stop = True
                    break
            sauvegarder_article(SOURCE_ID, article)
            nouveaux += 1
            log.info(f"  ✓ {(article['titre'] or '')[:65]} | {article['date_publication']}")
            time.sleep(DELAI)

        if stop or mode_test:
            break
        offset += per_page
        time.sleep(DELAI)

    return nouveaux


# ─── SCRAPER PRINCIPAL ────────────────────────────────────────────

def scraper(date_depuis=None, types=None, mode_test=False):
    date_limite = None
    if date_depuis:
        date_limite = datetime.strptime(date_depuis, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        log.info(f"Filtre actif : articles depuis le {date_depuis}")

    sources_actives = {k: v for k, v in SOURCES.items() if types is None or k in types}
    total = 0
    for type_nom, config in sources_actives.items():
        log.info(f"\n── {type_nom.upper()} ──")
        n, ok = collecter_via_rss(type_nom, config, date_limite, mode_test)
        if not ok or n == 0:
            log.info("  RSS insuffisant → liste HTML")
            n += collecter_via_html(type_nom, config, date_limite, mode_test)
        total += n
        log.info(f"→ {type_nom} : {n} article(s)")

    log.info(f"\n{'='*55}")
    log.info(f"Collecte terminée — {total} nouvel(s) article(s)")


# ─── API DE REQUÊTE PAR DATE ──────────────────────────────────────

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


# ─── POINT D'ENTRÉE CLI ───────────────────────────────────────────

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Scraper BRI/BIS → SQLite (DIIF/BEAC)")
    ap.add_argument("--depuis",  metavar="YYYY-MM-DD")
    ap.add_argument("--type",    nargs="+", choices=list(SOURCES.keys()))
    ap.add_argument("--test",    action="store_true")
    ap.add_argument("--db",      default=DB_PATH)
    ap.add_argument("--stats",   action="store_true")
    args = ap.parse_args()

    if args.stats:
        s = stats_db(args.db)
        print(f"\n{'─'*40}\nBase : {args.db}\nTotal : {s['total']}\nPar type : {s['par_type']}\nPar année : {s['par_annee']}\nPlus récent : {s['plus_recent']}\n{'─'*40}")
    else:
        scraper(date_depuis=args.depuis, types=args.type, mode_test=args.test)
