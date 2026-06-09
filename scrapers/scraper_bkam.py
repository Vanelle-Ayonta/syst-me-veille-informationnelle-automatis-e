"""
scraper_bkam.py — Bank Al-Maghrib (bkam.ma)
============================================
Collecte les communiqués et publications sur l'inclusion financière.

STRUCTURE DU SITE
─────────────────
CMS eZ Platform. Pas de RSS. Pagination par paramètre ?page=N ou liste statique.

Sections collectées :
  - Communiqués    : /Communiques?page=N
  - Publications IF: /Publications-et-recherche/Publications-institutionnelles
  - Inclusion fin. : /Inclusion-financiere/

Format de date : année dans l'URL (/Communique/2024/) + texte visible dans la page
Filtre thématique : actif sur publications, inactif sur communiqués

NOTE RÉSEAU : Exécuter depuis poste DIIF.

USAGE
─────
    python scraper_bkam.py                       # collecte complète
    python scraper_bkam.py --depuis 2023-01-01
    python scraper_bkam.py --type communique
    python scraper_bkam.py --test
    python scraper_bkam.py --stats
"""

import requests
from bs4 import BeautifulSoup
import sqlite3
import time
import argparse
import logging
import re
import json as _json
from datetime import datetime, timezone

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from base_scraper import get_or_create_source, url_existe, sauvegarder_article

SOURCE_ID = get_or_create_source("Bank Al-Maghrib", "https://www.bkam.ma", "fr", "web")

BASE_URL = "https://www.bkam.ma"
DB_PATH  = "bkam.db"
DELAI    = 1.5

MOIS_FR = {
    "janvier":1,"février":2,"mars":3,"avril":4,"mai":5,"juin":6,
    "juillet":7,"août":8,"septembre":9,"octobre":10,"novembre":11,"décembre":12,
}

MOTS_CLES = [
    # Inclusion financière
    "inclusion financière", "financial inclusion", "bancarisation",
    "microfinance", "microcrédit", "mobile payment", "paiement mobile",
    "fintech", "digital", "numérique", "interopérabilité",
    "éducation financière", "stratégie nationale", "snif",
    # Système de paiement et infrastructure
    "moyen de paiement", "infrastructure financière",
    "stabilité financière", "marché financier", "système financier",
    "surveillance", "paiement", "transfert", "remittance",
    # Institutions et géographie
    "maroc", "uemoa", "afrique", "bank al-maghrib",
    # Rapports institutionnels (tous pertinents pour une banque centrale)
    "rapport annuel", "rapport sur",
]

SOURCES = {
    "communique": {
        "liste":    "/Communiques",
        "prefixes": ["/Communiques/Communique/"],
        "type":     "communique",
        "filtrer":  False,
    },
    "publication": {
        "liste":    "/Publications-et-recherche/Publications-institutionnelles",
        "prefixes": [
            "/Publications-et-recherche/Publications-institutionnelles/",
            "/Inclusion-financiere/",
        ],
        "type":     "publication",
        "filtrer":  True,
    },
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Referer": "https://www.bkam.ma/",
}

_session = requests.Session()
_session.headers.update(HEADERS)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
log = logging.getLogger(__name__)


# ─── UTILITAIRES ──────────────────────────────────────────────────

def parser_date_texte(texte):
    if not texte:
        return None, None, None, None
    texte = texte.strip()

    # ISO
    m = re.search(r'(\d{4})-(\d{2})-(\d{2})', texte)
    if m:
        a, mo, j = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return f"{a:04d}-{mo:02d}-{j:02d} 00:00:00", a, mo, j

    # FR : "16 décembre 2025"
    m = re.search(r'(\d{1,2})\s+([a-zéûôàèùâê]+)\s+(\d{4})', texte.lower())
    if m:
        j = int(m.group(1))
        mo = MOIS_FR.get(m.group(2)[:9])
        a = int(m.group(3))
        if mo:
            return f"{a:04d}-{mo:02d}-{j:02d} 00:00:00", a, mo, j

    return None, None, None, None


def extraire_date_url(url):
    """Extrait l'année depuis l'URL BKAM : /Communique/2024/ → (2024-01-01, 2024, 1, 1)"""
    m = re.search(r'/Communique[s]?/(\d{4})/', url)
    if m:
        a = int(m.group(1))
        return f"{a:04d}-01-01 00:00:00", a, 1, 1
    # Année dans d'autres URLs
    m = re.search(r'/(202\d)/', url)
    if m:
        a = int(m.group(1))
        return f"{a:04d}-01-01 00:00:00", a, 1, 1
    return None, None, None, None


def est_pertinent(titre, resume, filtrer):
    if not filtrer:
        return True
    texte = f"{titre} {resume}".lower()
    return any(mot in texte for mot in MOTS_CLES)


def get(url, timeout=20, retries=2):
    for tentative in range(retries + 1):
        try:
            r = _session.get(url, timeout=timeout)
            r.raise_for_status()
            return r
        except requests.RequestException as e:
            if tentative < retries:
                time.sleep(3)
            else:
                log.warning(f"Erreur [{url[-65:]}] : {e}")
                return None


# ─── EXTRACTION D'UN ARTICLE ──────────────────────────────────────

def extraire_article(url, type_contenu, date_url=None):
    r = get(url)
    if r is None:
        return None
    soup = BeautifulSoup(r.text, "html.parser")

    # Titre
    titre = None
    og = soup.find("meta", property="og:title")
    if og:
        titre = og.get("content", "").replace(" | Bank Al-Maghrib", "").replace(" | BANK AL-MAGHRIB", "").strip()
    if not titre:
        h1 = soup.find("h1")
        titre = h1.get_text(strip=True) if h1 else None

    # Date — plusieurs stratégies
    date_pub = annee = mois = jour = None

    # 1. Balise <time>
    t = soup.find("time")
    if t:
        val = t.get("datetime", "") or t.get_text(strip=True)
        date_pub, annee, mois, jour = parser_date_texte(val)

    # 2. JSON-LD
    if not date_pub:
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = _json.loads(script.string or "")
                items = data if isinstance(data, list) else [data]
                for item in items:
                    for key in ["datePublished", "dateCreated"]:
                        val = item.get(key, "")
                        if val:
                            date_pub, annee, mois, jour = parser_date_texte(val)
                            if date_pub:
                                break
                    if date_pub:
                        break
            except Exception:
                pass
            if date_pub:
                break

    # 3. Texte visible
    if not date_pub:
        texte = soup.get_text()
        m = re.search(
            r'\d{1,2}\s+(?:janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre)\s+\d{4}',
            texte, re.IGNORECASE
        )
        if m:
            date_pub, annee, mois, jour = parser_date_texte(m.group())

    # 4. URL
    if not date_pub:
        date_pub, annee, mois, jour = extraire_date_url(url)

    # 5. Année dans le titre (ex: "Rapport annuel 2024", "Exercice 2023")
    if not date_pub and titre:
        m_titre = re.search(r'(20[12]\d)', titre)
        if m_titre:
            a = int(m_titre.group(1))
            date_pub, annee, mois, jour = f"{a:04d}-01-01 00:00:00", a, 1, 1

    # 6. date_url passée en paramètre
    if not date_pub and date_url:
        date_pub, annee, mois, jour = date_url

    # Résumé
    resume = None
    meta = soup.find("meta", attrs={"name": "description"}) or \
           soup.find("meta", property="og:description")
    if meta:
        resume = meta.get("content", "").strip()

    # Contenu
    contenu = ""
    corps = (
        soup.find("div", class_=re.compile(r"content|article|main|body"))
        or soup.find("article") or soup.find("main")
    )
    if corps:
        for tag in corps.find_all(["script", "style", "nav", "aside", "form", "header", "footer"]):
            tag.decompose()
        contenu = corps.get_text(separator="\n", strip=True)[:8000]

    # Vérification cohérence — rejeter les dates suspectes (date de page liste)
    # Si mois=05 et jour=24 → date parasite connue du site BKAM → utiliser URL
    DATES_PARASITES = ["2024-05-24", "2023-05-24", "2025-05-24"]
    if date_pub and any(date_pub.startswith(d) for d in DATES_PARASITES):
        date_pub = None; annee = mois = jour = None

    date_url_seule, a_url, m_url, j_url = extraire_date_url(url)
    if not date_pub and date_url_seule:
        date_pub, annee, mois, jour = date_url_seule, a_url, m_url, j_url

    return {
        "url": url, "titre": titre,
        "date_publication": date_pub, "annee": annee, "mois": mois, "jour": jour,
        "type_contenu": type_contenu, "langue": "fr",
        "resume": resume, "contenu": contenu,
        "date_scraping": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
    }


# ─── COLLECTE ─────────────────────────────────────────────────────

def collecter(type_nom, config, date_limite, mode_test):
    log.info(f"  → Scraping HTML ({type_nom})")
    nouveaux = 0
    page = 0

    while True:
        url_liste = BASE_URL + config["liste"] + (f"?page={page}" if page > 0 else "")
        log.info(f"  Page {page} : {url_liste}")

        r = get(url_liste)
        if r is None:
            break

        soup = BeautifulSoup(r.text, "html.parser")

        urls_page = []
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if not href.startswith("http"):
                href = BASE_URL + href if href.startswith("/") else None
            if not href:
                continue
            # Ignorer les PDFs (pas de contenu HTML)
            if href.endswith('.pdf'):
                continue
            chemin = href.replace(BASE_URL, "")
            if any(chemin.startswith(p) for p in config["prefixes"]):
                if len(chemin.strip("/")) > len(config["prefixes"][0].strip("/")) + 3:
                    if href not in urls_page:
                        # Récupérer date de l'URL directement
                        date_url_tuple = extraire_date_url(href)
                        urls_page.append((href, date_url_tuple))

        if not urls_page:
            log.info("  Aucun article — fin pagination")
            break

        log.info(f"  {len(urls_page)} article(s)")
        stop = False

        for url, date_url_tuple in urls_page:
            if url_existe(url):
                continue

            # Pré-filtre temporel sur l'année URL
            if date_limite and date_url_tuple[0]:
                dt = datetime.strptime(date_url_tuple[0], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                if dt < date_limite:
                    log.info(f"  ↩ Trop ancien ({date_url_tuple[0][:4]}) — arrêt")
                    stop = True
                    break

            article = extraire_article(url, config["type"], date_url=date_url_tuple)
            if article is None:
                continue

            if not est_pertinent(article["titre"] or "", article["resume"] or "", config["filtrer"]):
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

        # Page suivante
        next_link = soup.find("a", attrs={"rel": "next"}) or \
                    soup.find("li", class_=re.compile("next|suivant"))
        if not next_link:
            log.info("  Dernière page")
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
    ap = argparse.ArgumentParser(description="Scraper Bank Al-Maghrib → SQLite (DIIF/BEAC)")
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
