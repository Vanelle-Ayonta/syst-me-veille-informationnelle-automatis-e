"""
Scraper — FinDev Gateway (findevgateway.org)
=============================================
Collecte les contenus (news, blog, publications) et les stocke en SQLite.
Chaque entrée est horodatée pour permettre un filtrage par date.

STRUCTURE DU SITE
─────────────────
FinDev Gateway est un site Drupal 10. Il publie trois types de contenus
pertinents pour la veille inclusion financière :

  - News         : /news?page=N         → actualités du secteur
  - Blog         : /blog?page=N         → analyses et articles de fond
  - Publications : /publications?page=N → rapports, études, toolkits (8000+)

Chaque page liste 10 éléments. La date est visible directement dans
la liste (format "28 Aug 2024") et dans le corps de l'article.

USAGE
─────
    python scraper_findev.py                       # collecte complète
    python scraper_findev.py --depuis 2023-01-01   # depuis une date
    python scraper_findev.py --type news           # un seul type
    python scraper_findev.py --test                # 1 page par type
    python scraper_findev.py --stats               # statistiques base

NOTE RÉSEAU
───────────
Le site bloque les accès depuis certains serveurs distants (403).
Exécuter ce script depuis un poste avec accès internet direct (DIIF).
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
SOURCE_ID = get_or_create_source(
    "FinDev Gateway",
    "https://www.findevgateway.org", "en", "rss"
)

# ─────────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────────

BASE_URL = "https://www.findevgateway.org"
DB_PATH  = "findevgateway.db"
DELAI    = 1.5   # secondes entre requêtes

# Types de contenus à collecter avec leur URL de liste et préfixe d'article
SOURCES = {
    "news": {
        "liste": "/news",
        "prefixes": ["/news/"],
        "langue": "en",
    },
    "blog": {
        "liste": "/blog",
        "prefixes": ["/blog/", "/guide/"],
        "langue": "en",
    },
    "publication": {
        "liste": "/publications",
        "prefixes": ["/paper/", "/publication/", "/toolkit/", "/case-study/"],
        "langue": "en",
    },
    # Version française (pertinente pour la CEMAC)
    # IMPORTANT : préfixe strict /fr/actualites/ pour éviter de capturer
    # les liens de navigation (/fr/collections, /fr/region/, etc.)
    "news_fr": {
        "liste": "/fr/actualites",
        "prefixes": ["/fr/actualites/", "/fr/nouvelles/"],
        "langue": "fr",
    },
    "blog_fr": {
        "liste": "/fr/blog",
        "prefixes": ["/fr/blog/"],
        "langue": "fr",
    },
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,fr;q=0.8",
    "Referer": "https://www.findevgateway.org/",
}

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
# BASE DE DONNÉES SQLITE
# ─────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────
# UTILITAIRES
# ─────────────────────────────────────────────────────────────────

# Correspondance mois anglais → numéro
MOIS_EN = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
MOIS_FR = {
    "jan": 1, "fév": 2, "mar": 3, "avr": 4, "mai": 5, "jun": 6,
    "jui": 7, "aoû": 8, "sep": 9, "oct": 10, "nov": 11, "déc": 12,
}


def parser_date_texte(texte: str):
    """
    Parse les dates en texte du site FinDev.
    Formats reconnus :
      '28 Aug 2024'   → ('2024-08-28 00:00:00', 2024, 8, 28)
      '18 December 2025'
      '01 Apr 2024'
      'April 2026'    → jour=1 par défaut
    """
    if not texte:
        return None, None, None, None

    texte = texte.strip()

    # Format complet : "28 Aug 2024" ou "18 December 2025"
    m = re.match(
        r'(\d{1,2})\s+([A-Za-zéèêàû]+)\s+(\d{4})',
        texte, re.IGNORECASE
    )
    if m:
        jour = int(m.group(1))
        mois_str = m.group(2)[:3].lower()
        annee = int(m.group(3))
        mois = MOIS_EN.get(mois_str) or MOIS_FR.get(mois_str)
        if mois:
            date_str = f"{annee:04d}-{mois:02d}-{jour:02d} 00:00:00"
            return date_str, annee, mois, jour

    # Format partiel : "April 2026"
    m = re.match(r'([A-Za-zéèêàû]+)\s+(\d{4})', texte, re.IGNORECASE)
    if m:
        mois_str = m.group(1)[:3].lower()
        annee = int(m.group(2))
        mois = MOIS_EN.get(mois_str) or MOIS_FR.get(mois_str)
        if mois:
            date_str = f"{annee:04d}-{mois:02d}-01 00:00:00"
            return date_str, annee, mois, 1

    # Format ISO dans attribut datetime : "2024-08-28"
    m = re.match(r'(\d{4})-(\d{2})-(\d{2})', texte)
    if m:
        annee, mois, jour = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return f"{annee:04d}-{mois:02d}-{jour:02d} 00:00:00", annee, mois, jour

    return None, None, None, None


def get(url, timeout=15):
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        r.raise_for_status()
        return r
    except requests.RequestException as e:
        log.warning(f"Erreur [{url[-70:]}] : {e}")
        return None


# ─────────────────────────────────────────────────────────────────
# EXTRACTION D'UN ARTICLE
# ─────────────────────────────────────────────────────────────────

def extraire_article(url: str, type_contenu: str, langue: str) -> dict | None:
    """
    Télécharge et analyse une page article FinDev.
    Retourne un dict avec tous les champs ou None si échec.
    """
    r = get(url)
    if r is None:
        return None

    soup = BeautifulSoup(r.text, "html.parser")

    # — Titre —
    h1 = soup.find("h1")
    titre = h1.get_text(strip=True) if h1 else None

    # — Date — (chercher la balise <time> ou le texte de date dans l'article)
    date_pub = annee = mois = jour = None

    time_tag = soup.find("time")
    if time_tag:
        dt_attr = time_tag.get("datetime", "")
        texte_date = time_tag.get_text(strip=True)
        date_pub, annee, mois, jour = parser_date_texte(dt_attr or texte_date)

    # Fallback : chercher pattern de date dans le texte de la page
    if not date_pub:
        # Chercher dans les éléments contenant une date typique FinDev
        for el in soup.find_all(string=re.compile(
            r'\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4}',
            re.IGNORECASE
        )):
            date_pub, annee, mois, jour = parser_date_texte(el.strip())
            if date_pub:
                break

    # — Résumé (meta description) —
    resume = None
    meta_desc = soup.find("meta", attrs={"name": "description"})
    if meta_desc:
        resume = meta_desc.get("content", "").strip()

    # — Contenu principal —
    contenu = ""
    # FinDev Drupal : contenu dans article.node ou .field--name-body
    corps = (
        soup.find("div", class_=re.compile("field--name-body"))
        or soup.find("div", class_=re.compile("node__content"))
        or soup.find("article")
        or soup.find("main")
    )
    if corps:
        for tag in corps.find_all(["script", "style", "nav", "aside", "form",
                                    "header", "footer"]):
            tag.decompose()
        contenu = corps.get_text(separator="\n", strip=True)[:8000]

    # — Métadonnées (topics, région, pays, organisation) —
    topics = []
    for a in soup.select("a[href*='/topics/']"):
        t = a.get_text(strip=True)
        if t and t not in topics:
            topics.append(t)

    region = None
    for a in soup.select("a[href*='/region/']"):
        region = a.get_text(strip=True)
        break

    pays = None
    for a in soup.select("a[href*='/country/']"):
        pays = a.get_text(strip=True)
        break

    organisation = None
    for a in soup.select("a[href*='/organization/']"):
        organisation = a.get_text(strip=True)
        break

    return {
        "url": url,
        "titre": titre,
        "date_publication": date_pub,
        "annee": annee,
        "mois": mois,
        "jour": jour,
        "type_contenu": type_contenu,
        "topics": ", ".join(topics) if topics else None,
        "region": region,
        "pays": pays,
        "organisation": organisation,
        "langue": langue,
        "resume": resume,
        "contenu": contenu,
        "date_scraping": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
    }


# ─────────────────────────────────────────────────────────────────
# COLLECTE PAR TYPE DE CONTENU
# ─────────────────────────────────────────────────────────────────

def collecter_type(
    type_nom: str,
    config: dict,
    date_limite: datetime | None,
    mode_test: bool,
) -> int:
    """
    Parcourt les pages de liste d'un type de contenu et collecte les articles.
    Retourne le nombre d'articles enregistrés.
    """
    log.info(f"\n── {type_nom.upper()} ({'FR' if config['langue'] == 'fr' else 'EN'}) ──")
    nouveaux = 0
    page = 0

    while True:
        url_liste = BASE_URL + config["liste"] + (f"?page={page}" if page > 0 else "")
        log.info(f"  Page {page} : {url_liste}")

        r = get(url_liste)
        if r is None:
            log.warning("  Page inaccessible — arrêt de ce type")
            break

        soup = BeautifulSoup(r.text, "html.parser")

        # Extraire les liens d'articles depuis la page de liste
        urls_page = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            # Normaliser l'URL
            if href.startswith("/"):
                href = BASE_URL + href
            if not href.startswith(BASE_URL):
                continue
            # Vérifier que c'est bien un article (pas nav, filtre, etc.)
            chemin = href.replace(BASE_URL, "")
            if any(chemin.startswith(p) for p in config["prefixes"]):
                if href not in urls_page and len(chemin.strip("/")) > 10:
                    urls_page.append(href)

        if not urls_page:
            log.info("  Aucun article trouvé — fin de la pagination")
            break

        log.info(f"  {len(urls_page)} article(s) trouvé(s) sur cette page")

        # Vérifier si la page contient des articles dans la plage de dates
        # En lisant les dates visibles dans la liste
        texte_page = soup.get_text()
        dernier_stop = False

        for url_art in urls_page:
            if url_existe(url_art):
                continue

            article = extraire_article(url_art, type_nom, config["langue"])
            if article is None:
                continue

            # Filtre temporel
            if date_limite and article["date_publication"]:
                dt = datetime.strptime(
                    article["date_publication"], "%Y-%m-%d %H:%M:%S"
                ).replace(tzinfo=timezone.utc)
                if dt < date_limite:
                    log.info(f"  ↩ Trop ancien ({article['date_publication']}) — arrêt")
                    dernier_stop = True
                    break

            sauvegarder_article(SOURCE_ID, article)
            nouveaux += 1
            log.info(
                f"  ✓ {(article['titre'] or '')[:65]} "
                f"| {article['date_publication']} | {article['region'] or ''}"
            )
            time.sleep(DELAI)

        if dernier_stop:
            break

        if mode_test:
            log.info("  [MODE TEST] Arrêt après 1 page")
            break

        # Vérifier s'il y a une page suivante
        # Drupal affiche "Showing X - Y of Z" — si Y < Z, il y a une suite
        match = re.search(r'Showing\s+\d+\s*-\s*(\d+)\s+of\s+(\d+)', texte_page)
        if match:
            fin_page = int(match.group(1))
            total = int(match.group(2))
            if fin_page >= total:
                log.info(f"  Dernière page atteinte ({total} éléments total)")
                break
        
        page += 1
        time.sleep(DELAI)

    return nouveaux


# ─────────────────────────────────────────────────────────────────
# SCRAPER PRINCIPAL
# ─────────────────────────────────────────────────────────────────

def scraper(
    date_depuis: str | None = None,
    types: list[str] | None = None,
    mode_test: bool = False,
):
    date_limite = None
    if date_depuis:
        date_limite = datetime.strptime(date_depuis, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        log.info(f"Filtre actif : articles depuis le {date_depuis}")

    sources_actives = {
        k: v for k, v in SOURCES.items()
        if types is None or any(k.startswith(t) for t in types)
    }

    total = 0
    for type_nom, config in sources_actives.items():
        n = collecter_type(type_nom, config, date_limite, mode_test)
        total += n
        log.info(f"→ {type_nom} : {n} article(s) collecté(s)")

    log.info(f"\n{'='*55}")
    log.info(f"Collecte terminée — {total} nouvel(s) article(s)")


# ─────────────────────────────────────────────────────────────────
# API DE REQUÊTE PAR DATE (pour le pipeline RAG)
# ─────────────────────────────────────────────────────────────────

def requete_par_date(
    db_path: str = DB_PATH,
    date_debut: str = None,
    date_fin: str = None,
    type_contenu: str = None,
    langue: str = None,
    region: str = None,
    annee: int = None,
    mois: int = None,
    limit: int = 50,
) -> list[dict]:
    """
    Interroge la base par date et critères.

    Exemples
    --------
    # Publications récentes sur l'Afrique sub-saharienne
    requete_par_date(type_contenu='publication', region='Sub-Saharan Africa',
                     date_debut='2024-01-01')

    # Toutes les news FR de 2025
    requete_par_date(type_contenu='news_fr', annee=2025)
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cond, params = [], []

    if date_debut:    cond.append("date_publication >= ?");  params.append(date_debut)
    if date_fin:      cond.append("date_publication <= ?");  params.append(date_fin + " 23:59:59")
    if type_contenu:  cond.append("type_contenu = ?");       params.append(type_contenu)
    if langue:        cond.append("langue = ?");             params.append(langue)
    if region:        cond.append("region LIKE ?");          params.append(f"%{region}%")
    if annee:         cond.append("annee = ?");              params.append(annee)
    if mois:          cond.append("mois = ?");               params.append(mois)

    where = ("WHERE " + " AND ".join(cond)) if cond else ""
    rows = conn.execute(
        f"SELECT * FROM articles {where} ORDER BY date_publication DESC LIMIT ?",
        params + [limit]
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def stats_db(db_path: str = DB_PATH) -> dict:
    conn = sqlite3.connect(db_path)
    s = {
        "total":          conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0],
        "par_type":       dict(conn.execute("SELECT type_contenu, COUNT(*) FROM articles GROUP BY type_contenu").fetchall()),
        "par_langue":     dict(conn.execute("SELECT langue, COUNT(*) FROM articles GROUP BY langue").fetchall()),
        "par_annee":      dict(conn.execute("SELECT annee, COUNT(*) FROM articles GROUP BY annee ORDER BY annee").fetchall()),
        "plus_recent":    conn.execute("SELECT MAX(date_publication) FROM articles").fetchone()[0],
        "plus_ancien":    conn.execute("SELECT MIN(date_publication) FROM articles").fetchone()[0],
    }
    conn.close()
    return s


# ─────────────────────────────────────────────────────────────────
# POINT D'ENTRÉE CLI
# ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="Scraper FinDev Gateway → SQLite (DIIF/BEAC)"
    )
    ap.add_argument("--depuis",  metavar="YYYY-MM-DD",
                    help="Collecte uniquement les articles publiés depuis cette date")
    ap.add_argument("--type",    nargs="+",
                    choices=list(SOURCES.keys()),
                    help="Type(s) de contenu à collecter (défaut : tous)")
    ap.add_argument("--test",    action="store_true",
                    help="1 page par type seulement")
    ap.add_argument("--db",      default=DB_PATH)
    ap.add_argument("--stats",   action="store_true",
                    help="Afficher les statistiques de la base existante")
    args = ap.parse_args()

    if args.stats:
        s = stats_db(args.db)
        print(f"\n{'─'*45}")
        print(f"Base           : {args.db}")
        print(f"Total          : {s['total']} articles")
        print(f"Par type       : {s['par_type']}")
        print(f"Par langue     : {s['par_langue']}")
        print(f"Par année      : {s['par_annee']}")
        print(f"Plus récent    : {s['plus_recent']}")
        print(f"Plus ancien    : {s['plus_ancien']}")
        print(f"{'─'*45}")
    else:
        scraper(date_depuis=args.depuis, types=args.type, mode_test=args.test)
