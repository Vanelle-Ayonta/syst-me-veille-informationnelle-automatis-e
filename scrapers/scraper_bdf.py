"""
Scraper — Banque de France (banque-france.fr)
=============================================
Collecte les communiqués et publications sur l'inclusion financière.

STRUCTURE DU SITE
─────────────────
CMS Drupal personnalisé. Pagination via ?page=N.

Sections retenues (pertinentes pour la veille DIIF) :
  - Communiqués de presse : /fr/communiques-de-presse
  - Publications inclusion : /fr/publications-et-statistiques/publications
    filtrées sur les thèmes inclusion financière, éducation financière, OIB

Stratégie : scraping HTML des pages de liste paginées + extraction article.

Format de date : texte français ('12 mars 2024') ou attribut datetime HTML.

NOTE RÉSEAU : Exécuter depuis poste DIIF.

USAGE
─────
    python scraper_bdf.py                       # collecte complète
    python scraper_bdf.py --depuis 2023-01-01
    python scraper_bdf.py --type communique
    python scraper_bdf.py --test
    python scraper_bdf.py --stats
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
    "Banque de France",
    "https://www.banque-france.fr", "fr", "web"
)
BASE_URL = "https://www.banque-france.fr"
DB_PATH  = "banque_france.db"
DELAI    = 1.5

# Mots-clés pour filtrer les publications pertinentes
MOTS_CLES_IF = [
    "inclusion", "éducation financière", "educfi", "surendettement",
    "observatoire", "oib", "fragil", "microcrédit", "bancarisation",
    "afrique", "cemac", "developing", "access to finance"
]

SOURCES = {
    "communique": {
        "liste":    "/fr/communiques-de-presse",
        "prefixes": ["/fr/communiques-de-presse/"],
        "type":     "communique",
        "filtrer":  False,   # tous les communiqués
    },
    "publication": {
        "liste":    "/fr/publications-et-statistiques/publications",
        "prefixes": ["/fr/publications-et-statistiques/publications/"],
        "type":     "publication",
        "filtrer":  True,    # uniquement ceux liés à l'inclusion financière
    },
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    "Referer": "https://www.banque-france.fr/",
}

MOIS_FR = {
    "janvier": 1, "février": 2, "mars": 3, "avril": 4,
    "mai": 5, "juin": 6, "juillet": 7, "août": 8,
    "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12,
    "jan": 1, "fév": 2, "mar": 3, "avr": 4,
    "jun": 6, "jul": 7, "aoû": 8, "sep": 9, "oct": 10, "nov": 11, "déc": 12,
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
log = logging.getLogger(__name__)


# ─── BASE DE DONNÉES ──────────────────────────────────────────────


# ─── UTILITAIRES ──────────────────────────────────────────────────

def parser_date(texte):
    """
    Parse les dates françaises de la BdF.
    Formats : '12 mars 2024' | '12 Mars 2024' | 'December 12, 2024' | '2024-03-12'
    """
    if not texte:
        return None, None, None, None
    texte = texte.strip()

    # Format ISO
    m = re.search(r'(\d{4})-(\d{2})-(\d{2})', texte)
    if m:
        a, mo, j = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return f"{a:04d}-{mo:02d}-{j:02d} 00:00:00", a, mo, j

    # Format FR : "12 mars 2024"
    m = re.search(r'(\d{1,2})\s+([a-zéûôàèùâê]+)\s+(\d{4})', texte.lower())
    if m:
        j = int(m.group(1))
        mo = MOIS_FR.get(m.group(2)[:9])
        a = int(m.group(3))
        if mo:
            return f"{a:04d}-{mo:02d}-{j:02d} 00:00:00", a, mo, j

    # Format EN : "December 12, 2024"
    MOIS_EN = {"january":1,"february":2,"march":3,"april":4,"may":5,"june":6,
               "july":7,"august":8,"september":9,"october":10,"november":11,"december":12}
    m = re.search(r'([a-z]+)\s+(\d{1,2})[,\s]+(\d{4})', texte.lower())
    if m:
        mo = MOIS_EN.get(m.group(1))
        j = int(m.group(2))
        a = int(m.group(3))
        if mo:
            return f"{a:04d}-{mo:02d}-{j:02d} 00:00:00", a, mo, j

    return None, None, None, None


def est_pertinent(titre, resume, contenu=""):
    """Vérifie si une publication est liée à l'inclusion financière."""
    texte = f"{titre} {resume} {contenu}".lower()
    return any(mot in texte for mot in MOTS_CLES_IF)


def get(url, timeout=12, retries=2):
    for tentative in range(retries + 1):
        try:
            r = requests.get(url, headers=HEADERS, timeout=timeout)
            r.raise_for_status()
            return r
        except requests.RequestException as e:
            if tentative < retries:
                log.warning(f"Erreur [{url[-65:]}] : {e} — retry {tentative+1}/{retries}")
                time.sleep(3)  # pause avant retry
            else:
                log.warning(f"Erreur [{url[-65:]}] : {e}")
                return None


# ─── EXTRACTION D'UN ARTICLE ──────────────────────────────────────

def extraire_article(url, type_contenu):
    r = get(url)
    if r is None:
        return None
    soup = BeautifulSoup(r.text, "html.parser")

    # Titre
    titre = None
    og = soup.find("meta", property="og:title")
    if og:
        titre = og.get("content", "").replace(" | Banque de France", "").strip()
    if not titre:
        h1 = soup.find("h1")
        titre = h1.get_text(strip=True) if h1 else None

    # Date — plusieurs sources possibles sur le site BdF
    date_pub = annee = mois = jour = None

    # 1. Balise <time>
    t = soup.find("time")
    if t:
        dt_attr = t.get("datetime", "")
        date_pub, annee, mois, jour = parser_date(dt_attr or t.get_text(strip=True))

    # 2. Meta
    if not date_pub:
        for prop in ["article:published_time", "datePublished"]:
            m = soup.find("meta", property=prop) or soup.find("meta", attrs={"name": prop})
            if m:
                date_pub, annee, mois, jour = parser_date(m.get("content", ""))
                if date_pub:
                    break

    # 3. Texte de date visible dans la page
    if not date_pub:
        patterns = [
            r'\b\d{1,2}\s+(?:janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre)\s+\d{4}\b',
            r'\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}\b',
        ]
        texte_page = soup.get_text()
        for pat in patterns:
            m = re.search(pat, texte_page, re.IGNORECASE)
            if m:
                date_pub, annee, mois, jour = parser_date(m.group())
                if date_pub:
                    break

    # Résumé
    resume = None
    m = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", property="og:description")
    if m:
        resume = m.get("content", "").strip()

    # Contenu
    contenu = ""
    corps = (
        soup.find("div", class_=re.compile(r"field--name-body|article-content|content-body|node__content"))
        or soup.find("article")
        or soup.find("main")
    )
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
        "langue": "fr",
        "resume": resume,
        "contenu": contenu,
        "date_scraping": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
    }


# ─── COLLECTE PAR SOURCE ──────────────────────────────────────────

def collecter(type_nom, config, date_limite, mode_test):
    log.info(f"  → Scraping HTML")
    nouveaux = 0
    page = 0

    while True:
        url_liste = BASE_URL + config["liste"] + (f"?page={page}" if page > 0 else "")
        log.info(f"  Page {page} : {url_liste}")

        r = get(url_liste)
        if r is None:
            break

        soup = BeautifulSoup(r.text, "html.parser")

        # Extraire les URLs d'articles
        urls_page = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if not href.startswith("http"):
                href = BASE_URL + href if href.startswith("/") else None
            if not href:
                continue
            chemin = href.replace(BASE_URL, "")
            if any(chemin.startswith(p) for p in config["prefixes"]):
                # Exclure les pages de liste elles-mêmes
                if chemin.strip("/") != config["liste"].strip("/"):
                    if len(chemin.strip("/")) > len(config["prefixes"][0].strip("/")) + 3:
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

            # Filtre thématique pour les publications
            if config["filtrer"]:
                if not est_pertinent(article["titre"] or "", article["resume"] or "", article["contenu"]):
                    continue

            # Filtre temporel
            if date_limite and article["date_publication"]:
                dt = datetime.strptime(article["date_publication"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
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

        # Vérifier s'il y a une page suivante
        next_page = soup.find("a", attrs={"rel": "next"}) or \
                    soup.find("li", class_=re.compile(r"pager__item--next"))
        if not next_page:
            log.info("  Dernière page atteinte")
            break

        page += 1
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
        n = collecter(type_nom, config, date_limite, mode_test)
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
    ap = argparse.ArgumentParser(description="Scraper Banque de France → SQLite (DIIF/BEAC)")
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
