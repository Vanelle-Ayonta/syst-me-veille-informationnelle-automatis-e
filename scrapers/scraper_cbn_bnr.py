"""
scraper_cbn_bnr.py — CBN Nigeria & BNR Rwanda
===============================================
Collecte les actualités et publications sur l'inclusion financière.

STRUCTURE DES SITES
───────────────────
CBN Nigeria (cbn.gov.ng) — CMS ASP.NET custom
  - Press releases : /News/pressrelease.asp
  - Reforms & initiatives : /AboutCBN/Reforms.html (page statique riche)
  - Financial inclusion : /dfd/Financialinclusion.html
  Format date : texte EN dans le contenu ('9 December 2025')

BNR Rwanda (bnr.rw) — TYPO3 CMS
  - Press releases : /pressrelease
  - Publications : /reportandpublication
  - PDFs avec date dans le nom de fichier ('MPC_Press_Release__May_2025.pdf')
  Format date : nom de fichier PDF + texte visible

Stratégie : scraping HTML + extraction date depuis texte et noms de fichiers
Filtre thématique : actif sur les deux sources

NOTE RÉSEAU : Exécuter depuis poste DIIF.

USAGE
─────
    python scraper_cbn_bnr.py --source all --test
    python scraper_cbn_bnr.py --source cbn --test
    python scraper_cbn_bnr.py --source bnr --test
    python scraper_cbn_bnr.py --source all --depuis 2023-01-01
    python scraper_cbn_bnr.py --stats
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
from pathlib import Path

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from base_scraper import get_or_create_source, url_existe, sauvegarder_article

SOURCE_IDS = {
    "cbn": get_or_create_source("Central Bank of Nigeria (CBN)", "https://www.cbn.gov.ng", "en", "web"),
    "bnr": get_or_create_source("National Bank of Rwanda (BNR)", "https://www.bnr.rw", "en", "web"),
}

SOURCES = {
    "cbn": {
        "nom":     "Central Bank of Nigeria (CBN)",
        "url":     "https://www.cbn.gov.ng",
        "db":      "cbn_nigeria.db",
        "langue":  "en",
        "source":  "Central Bank of Nigeria",
        "filtrer": True,
        # CBN : press releases en PDF non parsables en HTML.
        # On collecte les pages statiques HTML riches directement.
        "listes": [
            {
                "url":    "https://www.cbn.gov.ng/AboutCBN/Reforms.html",
                "type":   "reform",
                "prefixes": [],
                "static": True,
            },
            {
                "url":    "https://www.cbn.gov.ng/dfd/Financialinclusion.html",
                "type":   "financial_inclusion",
                "prefixes": [],
                "static": True,
            },
        ],
    },
    "bnr": {
        "nom":        "National Bank of Rwanda (BNR)",
        "url":        "https://www.bnr.rw",
        "db":         "bnr_rwanda.db",
        "langue":     "en",
        "source":     "National Bank of Rwanda",
        "filtrer":    False,
        "ssl_verify": False,  # Certificat SSL invalide sur bnr.rw
        # BNR TYPO3 : pages de liste chargées en AJAX.
        # On collecte les pages statiques connues + on cherche les liens PDFs.
        # BNR TYPO3 : contenu chargé en AJAX, aucun lien en HTML statique.
        # Stratégie : traiter chaque page thématique comme article statique.
        "listes": [
            {
                "url":    "https://www.bnr.rw/pressrelease",
                "type":   "press_release",
                "prefixes": [],
                "static": True,
            },
            {
                "url":    "https://www.bnr.rw/Publications",
                "type":   "publication",
                "prefixes": [],
                "static": True,
            },
            {
                "url":    "https://www.bnr.rw/inclusiondata",
                "type":   "financial_inclusion",
                "prefixes": [],
                "static": True,
            },
            {
                "url":    "https://www.bnr.rw/regulatorysandbox",
                "type":   "fintech",
                "prefixes": [],
                "static": True,
            },
        ],
    },
}

# Mots-clés filtre thématique
MOTS_CLES = [
    "financial inclusion", "fintech", "digital payment", "mobile money",
    "unbanked", "financial access", "payment system", "digital finance",
    "cbdc", "e-money", "microfinance", "financial literacy",
    "financial education", "financial stability", "financial sector",
    "digital currency", "open banking", "interoperability",
    "remittance", "fast payment", "instant payment",
    "africa", "developing", "emerging", "sub-saharan",
    "inclusion", "innovation", "digital", "payment",
    "reform", "policy", "strategy", "regulation",
]

MOIS_EN = {
    "january":1,"february":2,"march":3,"april":4,"may":5,"june":6,
    "july":7,"august":8,"september":9,"october":10,"november":11,"december":12,
    "jan":1,"feb":2,"mar":3,"apr":4,"jun":6,"jul":7,"aug":8,
    "sep":9,"oct":10,"nov":11,"dec":12,
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}

_session = requests.Session()
_session.headers.update(HEADERS)

# Session BNR avec SSL désactivé (certificat invalide sur bnr.rw)
_session_bnr = requests.Session()
_session_bnr.headers.update(HEADERS)
_session_bnr.verify = False

# Supprimer les warnings SSL pour BNR
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
log = logging.getLogger(__name__)


# ─── UTILITAIRES ──────────────────────────────────────────────────

def parser_date_texte(texte):
    """Parse les dates EN : '9 December 2025', '20 February 2025', '2025-03-15'"""
    if not texte:
        return None, None, None, None
    texte = texte.strip()

    m = re.search(r'(\d{4})-(\d{2})-(\d{2})', texte)
    if m:
        a, mo, j = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return f"{a:04d}-{mo:02d}-{j:02d} 00:00:00", a, mo, j

    # Format "28 March 2024"
    m = re.search(r'(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})', texte)
    if m:
        j = int(m.group(1))
        mo = MOIS_EN.get(m.group(2).lower()[:9])
        a = int(m.group(3))
        if mo:
            return f"{a:04d}-{mo:02d}-{j:02d} 00:00:00", a, mo, j

    # Format "March 28, 2024" (mois en premier)
    m = re.search(r'([A-Za-z]+)\s+(\d{1,2})[,\s]+(\d{4})', texte)
    if m:
        mo = MOIS_EN.get(m.group(1).lower()[:9])
        j = int(m.group(2))
        a = int(m.group(3))
        if mo:
            return f"{a:04d}-{mo:02d}-{j:02d} 00:00:00", a, mo, j

    # Format "May 2025" ou "December 2024"
    m = re.search(r'([A-Za-z]+)\s+(\d{4})', texte)
    if m:
        mo = MOIS_EN.get(m.group(1).lower()[:9])
        a = int(m.group(2))
        if mo:
            return f"{a:04d}-{mo:02d}-01 00:00:00", a, mo, 1

    return None, None, None, None


def parser_date_filename(filename):
    """
    Extrait la date depuis un nom de fichier PDF.
    Ex: 'MPC_Press_Release__May_2025_English.pdf' → 2025-05-01
    Ex: 'MPFSS_Report_March_2025.pdf' → 2025-03-01
    Ex: 'MPC_Press_Relase-_English_Version_August_2025.pdf' → 2025-08-01
    """
    if not filename:
        return None, None, None, None
    name = filename.replace('_', ' ').replace('-', ' ').lower()

    # Chercher mois + année
    for mois_nom, mois_num in MOIS_EN.items():
        if mois_nom in name:
            m = re.search(r'\b(20[12]\d)\b', name)
            if m:
                a = int(m.group(1))
                return f"{a:04d}-{mois_num:02d}-01 00:00:00", a, mois_num, 1

    # Juste l'année
    m = re.search(r'\b(20[12]\d)\b', filename)
    if m:
        a = int(m.group(1))
        return f"{a:04d}-01-01 00:00:00", a, 1, 1

    return None, None, None, None


def est_pertinent(titre, resume, filtrer=True):
    if not filtrer:
        return True
    texte = f"{titre} {resume}".lower()
    return any(mot in texte for mot in MOTS_CLES)


def get(url, timeout=20, retries=2, ssl_verify=True):
    sess = _session if ssl_verify else _session_bnr
    for tentative in range(retries + 1):
        try:
            r = sess.get(url, timeout=timeout)
            r.raise_for_status()
            return r
        except requests.RequestException as e:
            if tentative < retries:
                time.sleep(3)
            else:
                log.warning(f"Erreur [{url[-65:]}] : {e}")
                return None


# ─── EXTRACTION D'UN ARTICLE ──────────────────────────────────────

def extraire_article(url, type_contenu, source_config):
    ssl_ok = source_config.get("ssl_verify", True)
    r = get(url, ssl_verify=ssl_ok)
    if r is None:
        return None
    soup = BeautifulSoup(r.text, "html.parser")

    # Titre
    titre = None
    og = soup.find("meta", property="og:title")
    if og:
        titre = og.get("content", "").replace(" | Central Bank of Nigeria", "").strip()
    if not titre:
        h1 = soup.find("h1")
        titre = h1.get_text(strip=True) if h1 else None
    if not titre:
        title_tag = soup.find("title")
        if title_tag:
            titre = title_tag.get_text(strip=True).split("|")[0].strip()

    # Date
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

    # 3. Patterns de date dans le texte
    if not date_pub:
        texte_page = soup.get_text()
        patterns = [
            r'\b\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}\b',
            r'\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}\b',
        ]
        for pat in patterns:
            m = re.search(pat, texte_page, re.IGNORECASE)
            if m:
                date_pub, annee, mois, jour = parser_date_texte(m.group())
                if date_pub:
                    break

    # 4. Date depuis nom de fichier (pour PDFs BNR)
    if not date_pub:
        filename = url.split('/')[-1]
        date_pub, annee, mois, jour = parser_date_filename(filename)

    # Résumé
    resume = None
    meta = soup.find("meta", attrs={"name": "description"}) or \
           soup.find("meta", property="og:description")
    if meta:
        resume = meta.get("content", "").strip()

    # Contenu
    contenu = ""
    corps = (
        soup.find("div", class_=re.compile(r"content|article|main|post"))
        or soup.find("article") or soup.find("main")
    )
    if corps:
        for tag in corps.find_all(["script", "style", "nav", "aside", "form", "header", "footer"]):
            tag.decompose()
        contenu = corps.get_text(separator="\n", strip=True)[:8000]
    if not contenu:
        # Fallback sur tout le body
        body = soup.find("body")
        if body:
            for tag in body.find_all(["script", "style", "nav", "header", "footer"]):
                tag.decompose()
            contenu = body.get_text(separator="\n", strip=True)[:8000]

    return {
        "url": url, "titre": titre,
        "date_publication": date_pub, "annee": annee, "mois": mois, "jour": jour,
        "type_contenu": type_contenu,
        "langue": source_config["langue"],
        "resume": resume, "contenu": contenu,
        "source": source_config["source"],
        "date_scraping": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
    }


# ─── COLLECTE ─────────────────────────────────────────────────────

def collecter_liste(source_id, liste_config, source_config, date_limite, mode_test):
    url_liste = liste_config["url"]
    type_contenu = liste_config["type"]
    prefixes = liste_config.get("prefixes", [])
    is_static = liste_config.get("static", False)
    nouveaux = 0

    log.info(f"  → {url_liste}")

    # Cas spécial : page statique (traiter la page elle-même comme article)
    ssl_ok = source_config.get("ssl_verify", True)
    if is_static:
        if not url_existe(url_liste):
            article = extraire_article(url_liste, type_contenu, source_config)
            if article and est_pertinent(article["titre"] or "", article["resume"] or "", source_config["filtrer"]):
                sauvegarder_article(source_id, article)
                nouveaux += 1
                log.info(f"  ✓ [STATIC] {(article['titre'] or '')[:60]} | {article['date_publication']}")
        return nouveaux

    # Pages de liste avec liens
    page = 0
    while True:
        url_page = url_liste + (f"?page={page}" if page > 0 else "")
        ssl_ok = source_config.get("ssl_verify", True)
        r = get(url_page, ssl_verify=ssl_ok)
        if r is None:
            break

        soup = BeautifulSoup(r.text, "html.parser")
        urls_page = []

        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            # Normaliser l'URL
            if href.startswith("http"):
                full = href
            elif href.startswith("/"):
                full = source_config["url"] + href
            else:
                continue

            # Ignorer les PDFs (sauf pour BNR où c'est la principale source)
            if full.endswith('.pdf') and source_config["nom"].startswith("Central Bank of Nigeria"):
                continue

            chemin = full.replace(source_config["url"], "")

            # Vérifier les préfixes
            if prefixes:
                if not any(chemin.startswith(p) for p in prefixes):
                    continue
            else:
                if source_config["url"] not in full:
                    continue

            if len(chemin.strip("/")) > 5 and full not in urls_page:
                urls_page.append(full)

        if not urls_page:
            log.info("  Fin de liste")
            break

        log.info(f"  Page {page} : {len(urls_page)} article(s)")
        stop = False

        for url in urls_page:
            if url_existe(url):
                continue

            # Pour les PDFs BNR, extraire date depuis nom de fichier directement
            if url.endswith('.pdf'):
                filename = url.split('/')[-1]
                date_pub, annee, mois, jour = parser_date_filename(filename)
                titre_pdf = filename.replace('_', ' ').replace('-', ' ').replace('.pdf', '').strip()

                if not est_pertinent(titre_pdf, "", source_config["filtrer"]):
                    continue

                if date_limite and date_pub:
                    dt = datetime.strptime(date_pub, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                    if dt < date_limite:
                        stop = True; break

                article = {
                    "url": url, "titre": titre_pdf,
                    "date_publication": date_pub, "annee": annee, "mois": mois, "jour": jour,
                    "type_contenu": type_contenu,
                    "langue": source_config["langue"],
                    "resume": None, "contenu": f"PDF document: {filename}",
                    "source": source_config["source"],
                    "date_scraping": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                }
                sauvegarder_article(source_id, article)
                nouveaux += 1
                log.info(f"  ✓ [PDF] {titre_pdf[:65]} | {date_pub}")
                time.sleep(0.5)
                continue

            # Article HTML
            article = extraire_article(url, type_contenu, source_config)
            if article is None:
                continue

            if not est_pertinent(article["titre"] or "", article["resume"] or "", source_config["filtrer"]):
                continue

            if date_limite and article["date_publication"]:
                dt = datetime.strptime(article["date_publication"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                if dt < date_limite:
                    stop = True; break

            sauvegarder_article(source_id, article)
            nouveaux += 1
            log.info(f"  ✓ {(article['titre'] or '')[:65]} | {article['date_publication']}")
            time.sleep(1.5)

            if mode_test and nouveaux >= 5:
                stop = True; break

        if stop or mode_test:
            break

        # Page suivante
        next_link = soup.find("a", attrs={"rel": "next"}) or \
                    soup.find("li", class_=re.compile(r"next|pager.*next"))
        if not next_link:
            break
        page += 1
        time.sleep(1.0)

    return nouveaux


# ─── SCRAPER PRINCIPAL ────────────────────────────────────────────

def scraper_source(source_key, date_depuis=None, mode_test=False):
    config = SOURCES[source_key]
    source_id = SOURCE_IDS[source_key]

    date_limite = None
    if date_depuis:
        date_limite = datetime.strptime(date_depuis, "%Y-%m-%d").replace(tzinfo=timezone.utc)

    total = 0
    log.info(f"\n── {config['nom'].upper()} ──")

    for liste_config in config["listes"]:
        n = collecter_liste(source_id, liste_config, config, date_limite, mode_test)
        total += n

    log.info(f"→ {source_key} : {total} article(s)")
    return total


def scraper(sources=None, date_depuis=None, mode_test=False):
    cles = list(SOURCES.keys()) if sources is None else sources
    total = 0
    for key in cles:
        total += scraper_source(key, date_depuis, mode_test)
    log.info(f"\n{'='*55}")
    log.info(f"Collecte terminée — {total} article(s) au total")


# ─── STATS ────────────────────────────────────────────────────────

def stats_db(source_key):
    db_path = SOURCES[source_key]["db"]
    if not Path(db_path).exists():
        print(f"  {source_key} : base non créée")
        return
    conn = sqlite3.connect(db_path)
    total  = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
    par_an = dict(conn.execute("SELECT annee, COUNT(*) FROM articles GROUP BY annee ORDER BY annee").fetchall())
    recent = conn.execute("SELECT MAX(date_publication) FROM articles").fetchone()[0]
    conn.close()
    print(f"  [{source_key}] {SOURCES[source_key]['nom']}")
    print(f"    Total : {total} | Par année : {par_an} | Récent : {recent}")


# ─── POINT D'ENTRÉE CLI ───────────────────────────────────────────

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Scraper CBN Nigeria & BNR Rwanda → SQLite")
    ap.add_argument("--source",  nargs="+", choices=list(SOURCES.keys()) + ["all"], default=["all"])
    ap.add_argument("--depuis",  metavar="YYYY-MM-DD")
    ap.add_argument("--test",    action="store_true")
    ap.add_argument("--stats",   action="store_true")
    args = ap.parse_args()

    if args.stats:
        for key in SOURCES:
            stats_db(key)
    else:
        sources = list(SOURCES.keys()) if "all" in args.source else args.source
        scraper(sources=sources, date_depuis=args.depuis, mode_test=args.test)
