"""
scraper_bceao.py — BCEAO (bceao.int)
======================================
Collecte les communiqués et publications de la BCEAO liés à
l'inclusion financière, la fintech et les paiements digitaux dans l'UEMOA.

STRUCTURE DU SITE
─────────────────
CMS Drupal personnalisé. Pas de RSS. Pagination ?page=N.

Sections collectées :
  - Communiqués de presse : /fr/communiques-de-presse?page=N
  - Publications          : /fr/publications?page=N
  - Documents IF          : /fr/documents/inclusion-financiere (page statique)
  - FinTech               : /fr/content/fintech-et-digitalisation-des-services-financiers

Format de date : texte FR visible ('03 décembre 2025', '21 avril 2026')
Filtre thématique : actif sur les publications (les communiqués sont tous pertinents)

NOTE RÉSEAU : Exécuter depuis poste DIIF.

USAGE
─────
    python scraper_bceao.py                       # collecte complète
    python scraper_bceao.py --depuis 2023-01-01
    python scraper_bceao.py --type communique
    python scraper_bceao.py --test
    python scraper_bceao.py --stats
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
from base_scraper import get_or_create_source, url_existe, sauvegarder_article

SOURCE_ID = get_or_create_source("BCEAO", "https://www.bceao.int", "fr", "web")

BASE_URL = "https://www.bceao.int"
DB_PATH  = "bceao.db"
DELAI    = 1.5

MOIS_FR = {
    "janvier":1,"février":2,"mars":3,"avril":4,"mai":5,"juin":6,
    "juillet":7,"août":8,"septembre":9,"octobre":10,"novembre":11,"décembre":12,
    "jan":1,"fév":2,"mar":3,"avr":4,"jun":6,"jul":7,"aoû":8,
    "sep":9,"oct":10,"nov":11,"déc":12,
}

# Mots-clés filtre thématique
MOTS_CLES = [
    "inclusion financière", "financial inclusion", "bancarisation",
    "microfinance", "microcrédit", "mobile money", "monnaie mobile",
    "fintech", "paiement numérique", "services financiers numériques",
    "monnaie électronique", "établissement de paiement",
    "interopérabilité", "pi-spi", "paiement instantané",
    "éducation financière", "stratégie régionale",
    "uemoa", "umoa", "afrique de l'ouest", "zone franc",
    "digital", "innovation financière", "transformation digitale",
]

SOURCES = {
    "communique": {
        "liste":    "/fr/communique-presse",
        "prefixes": ["/fr/communique-presse/"],
        "type":     "communique",
        "filtrer":  False,  # tous les communiqués sont pertinents
    },
    "publication": {
        "liste":    "/fr/publications",
        "prefixes": ["/fr/publications/"],
        "type":     "publication",
        "filtrer":  True,   # filtre sur publications IF uniquement
    },
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Referer": "https://www.bceao.int/",
}

# Session persistante (réutilise la connexion TCP — réduit les timeouts SSL)
_session = requests.Session()
_session.headers.update(HEADERS)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
log = logging.getLogger(__name__)


# ─── UTILITAIRES ──────────────────────────────────────────────────

def parser_date(texte):
    """
    Parse les dates BCEAO.
    Formats : '03 décembre 2025' | '21 Avril 2026' | '2025-12-03'
    """
    if not texte:
        return None, None, None, None
    texte = texte.strip()

    # Format ISO
    m = re.search(r'(\d{4})-(\d{2})-(\d{2})', texte)
    if m:
        a, mo, j = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return f"{a:04d}-{mo:02d}-{j:02d} 00:00:00", a, mo, j

    # Format FR : "03 décembre 2025"
    m = re.search(r'(\d{1,2})\s+([a-zéûôàèùâê]+)\s+(\d{4})', texte.lower())
    if m:
        j = int(m.group(1))
        mo = MOIS_FR.get(m.group(2)[:9])
        a = int(m.group(3))
        if mo:
            return f"{a:04d}-{mo:02d}-{j:02d} 00:00:00", a, mo, j

    return None, None, None, None



MOIS_FR_SLUG = {
    'janvier':1,'fevrier':2,'mars':3,'avril':4,'mai':5,'juin':6,
    'juillet':7,'aout':8,'septembre':9,'octobre':10,'novembre':11,'decembre':12,
    'fev':2,'avr':4,'jui':6,'aou':8,'sep':9,'oct':10,'nov':11,'dec':12,
}

def extraire_date_slug(url):
    """Extrait la date depuis le slug de l'URL BCEAO quand aucune autre source ne fonctionne."""
    slug = url.rstrip('/').split('/')[-1].lower().replace('-', ' ')

    # "du 27 mars 2026" ou "au 31 decembre 2025"
    m = re.search(r'(?:du|au)\s+(\d{1,2})\s+([a-z]+)\s+(\d{4})', slug)
    if m:
        j, mois_str, a = int(m.group(1)), m.group(2)[:8], int(m.group(3))
        mo = MOIS_FR_SLUG.get(mois_str)
        if mo:
            return f"{a:04d}-{mo:02d}-{j:02d} 00:00:00", a, mo, j

    # Référence type "013-04-2026" → mois 04, année 2026
    m = re.search(r'(\d{2}) (\d{4})(?:\s|$)', slug)
    if m:
        mo, a = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12 and 2000 <= a <= 2030:
            return f"{a:04d}-{mo:02d}-01 00:00:00", a, mo, 1

    # Juste l'année "2026"
    m = re.search(r'\b(202\d)\b', slug)
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

def extraire_article(url, type_contenu, date_prefill=None):
    r = get(url)
    if r is None:
        return None
    soup = BeautifulSoup(r.text, "html.parser")

    # Titre
    titre = None
    og = soup.find("meta", property="og:title")
    if og:
        titre = og.get("content", "").replace(" | BCEAO", "").strip()
    if not titre:
        h1 = soup.find("h1")
        titre = h1.get_text(strip=True) if h1 else None

    # Date — chercher dans plusieurs endroits
    date_pub = annee = mois = jour = None

    # 1. Balise <time>
    t = soup.find("time")
    if t:
        val = t.get("datetime", "") or t.get_text(strip=True)
        date_pub, annee, mois, jour = parser_date(val)

    # 2. JSON-LD schema.org
    if not date_pub:
        import json as _json
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = _json.loads(script.string or "")
                items = data if isinstance(data, list) else [data]
                for item in items:
                    for key in ["datePublished", "dateCreated", "dateModified"]:
                        val = item.get(key, "")
                        if val:
                            date_pub, annee, mois, jour = parser_date(val)
                            if date_pub:
                                break
                    if date_pub:
                        break
            except Exception:
                pass
            if date_pub:
                break

    # 3. Patterns de date dans le texte visible de la page
    if not date_pub:
        texte = soup.get_text()
        m = re.search(
            r'\d{1,2}\s+(?:janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre)\s+\d{4}',
            texte, re.IGNORECASE
        )
        if m:
            date_pub, annee, mois, jour = parser_date(m.group())

    # 4. Meta tags
    if not date_pub:
        for prop in ["article:published_time", "datePublished", "DC.date", "DC.Date"]:
            meta = soup.find("meta", property=prop) or soup.find("meta", attrs={"name": prop})
            if meta:
                date_pub, annee, mois, jour = parser_date(meta.get("content", ""))
                if date_pub:
                    break

    # Résumé
    resume = None
    meta = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", property="og:description")
    if meta:
        resume = meta.get("content", "").strip()

    # Contenu
    contenu = ""
    corps = (
        soup.find("div", class_=re.compile(r"field--name-body|node__content|field-body"))
        or soup.find("article")
        or soup.find("main")
    )
    if corps:
        for tag in corps.find_all(["script", "style", "nav", "aside", "form", "header", "footer"]):
            tag.decompose()
        contenu = corps.get_text(separator="\n", strip=True)[:8000]

    # 5. Extraire depuis le slug de l'URL (BCEAO encode souvent la date dans l'URL)
    if not date_pub:
        date_pub, annee, mois, jour = extraire_date_slug(url)

    # 6. Date pré-extraite depuis la page de liste en dernier recours
    if not date_pub and date_prefill:
        date_pub, annee, mois, jour = parser_date(date_prefill)

    # Rejeter la date "2002-05-13" (date serveur Drupal, pas une vraie date d'article)
    if date_pub and date_pub.startswith("2002-05-13"):
        date_pub = None
        annee = mois = jour = None
        # Réessayer avec le slug uniquement
        date_pub, annee, mois, jour = extraire_date_slug(url)

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

        # Extraire les URLs + dates visibles depuis la page de liste
        urls_et_dates = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if not href.startswith("http"):
                href = BASE_URL + href if href.startswith("/") else None
            if not href:
                continue
            # Nettoyer les espaces parasites dans l'URL
            href = href.strip().rstrip('%20').strip()
            chemin = href.replace(BASE_URL, "").strip()
            if any(chemin.startswith(p) for p in config["prefixes"]):
                if len(chemin.strip("/")) > len(config["prefixes"][0].strip("/")) + 3:
                    if href not in [u for u, _ in urls_et_dates]:
                        # Chercher la date dans plusieurs niveaux de parents
                        date_visible = None
                        for niveau in range(5):
                            parent = a
                            for _ in range(niveau + 1):
                                parent = parent.find_parent() if parent else None
                            if parent is None:
                                break
                            texte_parent = parent.get_text()
                            m = re.search(
                                r'\d{1,2}\s+(?:janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre)\s+\d{4}',
                                texte_parent, re.IGNORECASE
                            )
                            if m:
                                date_visible = m.group()
                                break
                        urls_et_dates.append((href, date_visible))

        if not urls_et_dates:
            log.info("  Aucun article — fin pagination")
            break

        log.info(f"  {len(urls_et_dates)} article(s)")
        stop = False

        for url, date_visible in urls_et_dates:
            if url_existe(url):
                continue

            # Pré-filtre sur la date visible (évite de visiter des pages trop anciennes)
            if date_visible and date_limite:
                date_test, _, _, _ = parser_date(date_visible)
                if date_test:
                    dt = datetime.strptime(date_test, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                    if dt < date_limite:
                        log.info(f"  ↩ Trop ancien ({date_visible}) — arrêt")
                        stop = True
                        break

            article = extraire_article(url, config["type"], date_prefill=date_visible)
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

        # Vérifier page suivante (Drupal)
        next_link = soup.find("a", attrs={"rel": "next"}) or \
                    soup.find("li", class_=re.compile("pager__item--next"))
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
    ap = argparse.ArgumentParser(description="Scraper BCEAO → SQLite (DIIF/BEAC)")
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
