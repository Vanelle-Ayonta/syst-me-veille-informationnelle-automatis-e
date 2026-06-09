"""
scrapers/scraper_intl.py — Sources internationales IF (Groupe 5)
=================================================================
Couvre 7 sources :
  - worldbank : Banque mondiale (blogs.worldbank.org)
  - cgap      : CGAP (cgap.org)
  - wwb       : Women's World Banking (womensworldbanking.org)
  - btca      : Better Than Cash Alliance (betterthancash.org)
  - cfi       : Center for Financial Inclusion (centerforfinancialinclusion.org)
  - ada       : ADA Luxembourg (adaimpact.lu)
  - afd       : AFD (afd.fr)

Stratégie par source :
  - worldbank : RSS WordPress + API REST WP
  - cgap      : RSS + HTML paginé
  - wwb       : RSS WordPress
  - btca      : HTML statique paginé
  - cfi       : RSS WordPress
  - ada       : HTML paginé
  - afd       : HTML paginé Drupal

USAGE
─────
    python scraper_intl.py --source worldbank --test
    python scraper_intl.py --source cgap --test
    python scraper_intl.py --source all --test
    python scraper_intl.py --source worldbank --depuis 2023-01-01
    python scraper_intl.py --stats
"""

import requests
from bs4 import BeautifulSoup
import time
import argparse
import logging
import re
import sys, os
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from base_scraper import (
    get_or_create_source, url_existe,
    sauvegarder_article, now_iso
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

DELAI = 1.5

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,"
              "application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
}

# ── Configuration des 7 sources ───────────────────────────────────
SOURCES_CONFIG = {
    "worldbank": {
        "nom":      "Banque mondiale",
        "url":      "https://blogs.worldbank.org",
        "langue":   "en",
        "type":     "rss",
        "rss_urls": [
            "https://blogs.worldbank.org/en/developmenttalk/rss.xml",
            "https://blogs.worldbank.org/en/financialinclusion/rss.xml",
            "https://blogs.worldbank.org/en/digital-development/rss.xml",
            "https://blogs.worldbank.org/en/africacan/rss.xml",
        ],
        "api_wp": None,
        "mots_cles": [
            "financial inclusion", "mobile money", "fintech",
            "microfinance", "digital finance", "unbanked",
            "financial access", "remittance", "cbdc",
            "africa", "sub-saharan", "developing countries",
            "findex", "digital payment",
        ],
    },
    "cgap": {
        "nom":      "CGAP",
        "url":      "https://www.cgap.org",
        "langue":   "en",
        "type":     "web",
        "listes_html": [
            "https://www.cgap.org/research/publications",
            "https://www.cgap.org/blog",
            "https://www.cgap.org/news",
        ],
        "prefixes": [
            "/research/publication/",
            "/blog/",
            "/news/",
        ],
        "mots_cles": [
            "financial inclusion", "microfinance", "fintech",
            "digital finance", "mobile money", "poverty",
            "unbanked", "financial access", "savings",
            "credit", "insurance", "women", "rural",
        ],
    },
    "wwb": {
        "nom":      "Women's World Banking",
        "url":      "https://www.womensworldbanking.org",
        "langue":   "en",
        "type":     "rss",
        "rss_urls": [
            "https://www.womensworldbanking.org/feed/",
            "https://www.womensworldbanking.org/insights/feed/",
        ],
        "mots_cles": [
            "women", "financial inclusion", "microfinance",
            "gender", "mobile money", "savings", "credit",
            "insurance", "digital finance",
        ],
    },
    "btca": {
        "nom":      "Better Than Cash Alliance",
        "url":      "https://www.betterthancash.org",
        "langue":   "en",
        "type":     "web",
        "listes_html": [
            "https://www.betterthancash.org/news",
            "https://www.betterthancash.org/tools-research",
        ],
        "prefixes": [],
        "mots_cles": [
            "digital", "payment", "cash", "financial",
            "inclusion", "mobile", "women", "government",
            "economy", "development", "africa", "asia",
        ],
    },
    "cfi": {
        "nom":      "Center for Financial Inclusion",
        "url":      "https://www.centerforfinancialinclusion.org",
        "langue":   "en",
        "type":     "web",
        "listes_html": [
            "https://www.centerforfinancialinclusion.org/publications",
            "https://www.centerforfinancialinclusion.org/blog",
        ],
        "prefixes": [],
        "mots_cles": [
            "financial inclusion", "microfinance", "fintech",
            "digital", "women", "consumer", "insurance",
            "credit", "savings", "mobile", "africa",
        ],
    },
    "ada": {
        "nom":      "ADA Luxembourg",
        "url":      "https://adaimpact.lu",
        "langue":   "fr",
        "type":     "web",
        "listes_html": [
            "https://adaimpact.lu/news",
            "https://adaimpact.lu/nos-activites",
            "https://adaimpact.lu/ressources-et-outils",
        ],
        "prefixes": [],
        "mots_cles": [
            "microfinance", "inclusion", "finance",
            "afrique", "développement", "crédit",
            "épargne", "femmes", "rural", "impact",
        ],
    },
    "afd": {
        "nom":      "AFD",
        "url":      "https://www.afd.fr",
        "langue":   "fr",
        "type":     "web",
        "listes_html": [
            "https://www.afd.fr/fr/actualites",
            "https://www.afd.fr/fr/ressources",
        ],
        "prefixes": ["/fr/actualites/", "/fr/ressources/",
                     "/fr/page-thematique/"],
        "mots_cles": [
            "inclusion financière", "microfinance", "fintech",
            "afrique", "développement", "finance",
            "mobile money", "digital", "femmes", "mpme",
        ],
    },
}

# Source IDs (initialisés au démarrage)
SOURCE_IDS = {}


def init_sources():
    """Enregistre toutes les sources dans veille_diif.db."""
    for cle, cfg in SOURCES_CONFIG.items():
        SOURCE_IDS[cle] = get_or_create_source(
            cfg["nom"], cfg["url"],
            cfg["langue"], cfg["type"]
        )
        log.info(f"Source initialisée : {cfg['nom']}")


# ── Utilitaires ───────────────────────────────────────────────────

def get(url, json_mode=False, timeout=15, retries=2):
    h = ({**HEADERS, "Accept": "application/json"}
         if json_mode else HEADERS)
    for tentative in range(retries + 1):
        try:
            r = requests.get(url, headers=h, timeout=timeout)
            r.raise_for_status()
            return r
        except requests.RequestException as e:
            if tentative < retries:
                time.sleep(3)
            else:
                log.warning(f"Erreur [{url[-60:]}] : {e}")
                return None


def parser_date_iso(iso_string):
    if not iso_string:
        return None
    try:
        if "+" not in iso_string and "Z" not in iso_string:
            iso_string += "+00:00"
        dt = datetime.fromisoformat(
            iso_string.replace("Z", "+00:00")
        ).astimezone(timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def parser_date_rss(rfc2822):
    if not rfc2822:
        return None
    try:
        dt = parsedate_to_datetime(rfc2822).astimezone(
            timezone.utc
        )
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def est_pertinent(titre, contenu, mots_cles):
    texte = ((titre or "") + " " + (contenu or "")).lower()
    return any(m.lower() in texte for m in mots_cles)


def extraire_article(url, langue="en", resume_prefill=None):
    """Extrait le contenu complet d'un article."""
    r = get(url)
    if r is None:
        return None
    soup = BeautifulSoup(r.text, "html.parser")

    # Titre
    titre = None
    og = soup.find("meta", property="og:title")
    if og:
        titre = og.get("content", "").strip()
    if not titre:
        h1 = soup.find("h1")
        titre = h1.get_text(strip=True) if h1 else None

    # Date
    date_pub = None
    for prop in ["article:published_time",
                 "og:article:published_time"]:
        meta = soup.find("meta", property=prop)
        if meta:
            date_pub = parser_date_iso(meta.get("content", ""))
            break
    if not date_pub:
        t = soup.find("time", attrs={"datetime": True})
        if t:
            date_pub = parser_date_iso(t["datetime"])

    # Résumé
    resume = resume_prefill
    if not resume:
        m = (soup.find("meta", attrs={"name": "description"}) or
             soup.find("meta", property="og:description"))
        if m:
            resume = m.get("content", "").strip()

    # Contenu
    contenu = ""
    corps = (
        soup.find("div", class_=re.compile(
            r"entry-content|post-content|article-content"
            r"|article-body|field-body|main-content"
        )) or
        soup.find("article") or
        soup.find("main")
    )
    if corps:
        for tag in corps.find_all([
            "script", "style", "nav", "aside",
            "form", "header", "footer"
        ]):
            tag.decompose()
        contenu = corps.get_text(
            separator="\n", strip=True
        )[:8000]

    return {
        "url":              url,
        "titre":            titre,
        "date_publication": date_pub,
        "resume":           resume,
        "contenu":          contenu,
        "langue":           langue,
        "date_scraping":    now_iso(),
    }


# ── Collecte RSS ──────────────────────────────────────────────────

def collecter_rss(cle, date_limite=None, mode_test=False):
    cfg       = SOURCES_CONFIG[cle]
    source_id = SOURCE_IDS[cle]
    mots_cles = cfg.get("mots_cles", [])
    nouveaux  = 0

    for rss_url in cfg.get("rss_urls", []):
        log.info(f"  RSS : {rss_url}")
        r = get(rss_url)
        if r is None:
            continue

        soup  = BeautifulSoup(r.content, "xml")
        items = soup.find_all("item")
        if not items:
            items = soup.find_all("entry")

        log.info(f"  {len(items)} item(s)")
        stop = False

        for item in items:
            lien = item.find("link")
            url  = ""
            if lien:
                url = (lien.get_text(strip=True) or
                       lien.get("href", "")).strip()

            titre_tag = item.find("title")
            titre = titre_tag.get_text(strip=True) if titre_tag else ""

            desc_tag = (item.find("description") or
                        item.find("summary"))
            resume_raw = desc_tag.get_text(strip=True) if desc_tag else ""
            resume = BeautifulSoup(
                resume_raw, "html.parser"
            ).get_text(strip=True)[:500]

            date_tag = (item.find("pubDate") or
                        item.find("published"))
            date_str = date_tag.get_text(strip=True) if date_tag else ""
            date_pub = (
                parser_date_rss(date_str) or
                parser_date_iso(date_str)
            )

            if not url or not titre:
                continue

            if date_limite and date_pub:
                try:
                    dt = datetime.strptime(
                        date_pub, "%Y-%m-%d %H:%M:%S"
                    ).replace(tzinfo=timezone.utc)
                    if dt < date_limite:
                        stop = True
                        break
                except Exception:
                    pass

            if not est_pertinent(titre, resume, mots_cles):
                continue
            if url_existe(url):
                continue

            art = extraire_article(
                url, cfg["langue"],
                resume_prefill=resume
            )
            if art:
                art["date_publication"] = date_pub
                ok = sauvegarder_article(source_id, art)
                if ok:
                    nouveaux += 1
                    log.info(f"  ✓ {titre[:65]}")

            time.sleep(DELAI)
            if mode_test and nouveaux >= 5:
                stop = True
                break

        if stop:
            break

    return nouveaux


# ── Collecte HTML ─────────────────────────────────────────────────

def collecter_html(cle, date_limite=None, mode_test=False):
    cfg       = SOURCES_CONFIG[cle]
    source_id = SOURCE_IDS[cle]
    mots_cles = cfg.get("mots_cles", [])
    prefixes  = cfg.get("prefixes", [])
    nouveaux  = 0
    MAX_PAGES_VIDES = 3   # arret anticipé après N pages sans article nouveau

    for liste_url in cfg.get("listes_html", []):
        page = 1
        pages_sans_nouveau = 0

        while True:
            url_page = (
                liste_url
                if page == 1
                else f"{liste_url}?page={page}"
            )
            log.info(f"  Page {page} : {url_page}")
            r = get(url_page)
            if r is None:
                break

            soup  = BeautifulSoup(r.text, "html.parser")
            base  = "/".join(liste_url.split("/")[:3])
            liens = {}

            for a in soup.find_all("a", href=True):
                href  = a["href"].strip()
                texte = a.get_text(strip=True)
                if not href or not texte or len(texte) < 15:
                    continue
                if href.startswith("/"):
                    href = base + href
                elif not href.startswith("http"):
                    continue
                chemin = href.replace(cfg["url"], "")
                if prefixes and not any(
                    chemin.startswith(p) for p in prefixes
                ):
                    continue
                liens[href] = texte

            if not liens:
                break

            stop = False
            page_nouveaux = 0
            for url, titre in list(liens.items())[:20]:
                if not est_pertinent(titre, "", mots_cles):
                    continue
                if url_existe(url):
                    continue

                art = extraire_article(url, cfg["langue"])
                if not art:
                    continue
                if not est_pertinent(
                    art.get("titre", ""),
                    art.get("contenu", ""),
                    mots_cles
                ):
                    continue

                ok = sauvegarder_article(source_id, art)
                if ok:
                    nouveaux += 1
                    page_nouveaux += 1
                    log.info(
                        f"  ✓ {(art.get('titre',''))[:65]}"
                    )

                time.sleep(DELAI)
                if mode_test and nouveaux >= 5:
                    stop = True
                    break

            # Arret anticipé : si cette page n'a rien apporté de nouveau,
            # les pages suivantes (plus anciennes) n'en apporteront pas non plus.
            if page_nouveaux == 0:
                pages_sans_nouveau += 1
                if pages_sans_nouveau >= MAX_PAGES_VIDES:
                    log.info(
                        f"  {MAX_PAGES_VIDES} pages consecutives sans article nouveau "
                        f"— arret pagination ({cle}, page {page})"
                    )
                    stop = True
            else:
                pages_sans_nouveau = 0

            if stop or mode_test:
                break
            page += 1
            time.sleep(DELAI)

    return nouveaux


# ── Collecte API REST WP (Banque mondiale) ────────────────────────

def collecter_api_wp(cle, date_limite=None, mode_test=False):
    cfg       = SOURCES_CONFIG[cle]
    source_id = SOURCE_IDS[cle]
    mots_cles = cfg.get("mots_cles", [])
    api_url   = cfg.get("api_wp", "")
    nouveaux  = 0
    page      = 1

    while True:
        url = api_url.format(page=page)
        r   = get(url, json_mode=True, timeout=10)
        if r is None:
            break
        try:
            items = r.json()
        except Exception:
            break
        if not items or not isinstance(items, list):
            break

        stop = False
        for item in items:
            url_art = item.get("link", "")
            titre   = BeautifulSoup(
                item.get("title", {}).get("rendered", ""),
                "html.parser"
            ).get_text(strip=True)
            resume  = BeautifulSoup(
                item.get("excerpt", {}).get("rendered", ""),
                "html.parser"
            ).get_text(strip=True)[:500]
            date_pub = parser_date_iso(
                item.get("date_gmt", item.get("date", ""))
            )

            if date_limite and date_pub:
                try:
                    dt = datetime.strptime(
                        date_pub, "%Y-%m-%d %H:%M:%S"
                    ).replace(tzinfo=timezone.utc)
                    if dt < date_limite:
                        stop = True
                        break
                except Exception:
                    pass

            if not url_art or not titre:
                continue
            if not est_pertinent(titre, resume, mots_cles):
                continue
            if url_existe(url_art):
                continue

            art = extraire_article(
                url_art, cfg["langue"],
                resume_prefill=resume
            )
            if art:
                art["date_publication"] = date_pub
                ok = sauvegarder_article(source_id, art)
                if ok:
                    nouveaux += 1
                    log.info(f"  ✓ {titre[:65]}")

            time.sleep(DELAI)
            if mode_test and nouveaux >= 5:
                stop = True
                break

        if stop or len(items) < 10 or mode_test:
            break
        page += 1
        time.sleep(DELAI)

    return nouveaux


# ── Scraper principal ─────────────────────────────────────────────

def scraper(cle, date_depuis=None, mode_test=False):
    """Lance la collecte pour une source donnée."""
    if cle not in SOURCES_CONFIG:
        log.error(f"Source inconnue : {cle}")
        return 0

    cfg = SOURCES_CONFIG[cle]
    log.info(f"\n── {cfg['nom'].upper()} ──")

    date_limite = None
    if date_depuis:
        date_limite = datetime.strptime(
            date_depuis, "%Y-%m-%d"
        ).replace(tzinfo=timezone.utc)

    type_src = cfg["type"]

    if type_src == "rss":
        n = collecter_rss(cle, date_limite, mode_test)
        if n == 0 and cfg.get("liste_html"):
            n = collecter_html(cle, date_limite, mode_test)
    else:
        # type "web" → collecte HTML
        n = collecter_html(cle, date_limite, mode_test)

    log.info(f"→ {cfg['nom']} : {n} nouvel(s) article(s)")
    return n


def scraper_all(sources=None, date_depuis=None,
                mode_test=False):
    """Lance la collecte pour toutes les sources ou une liste."""
    init_sources()
    cles  = sources or list(SOURCES_CONFIG.keys())
    total = 0
    for cle in cles:
        try:
            n = scraper(cle, date_depuis, mode_test)
            total += n
        except Exception as e:
            log.error(f"[ERREUR] {cle} : {e}")
    log.info(f"\nTotal : {total} article(s) collecté(s)")
    return total


def stats():
    """Statistiques par source."""
    sys.path.insert(
        0, os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)
        ))
    )
    from core.database import get_db
    with get_db() as conn:
        print(f"\n{'─'*55}")
        print(f"{'Source':<35} {'Articles':>8} {'Dernière':>10}")
        print(f"{'─'*55}")
        for cle, cfg in SOURCES_CONFIG.items():
            sid = SOURCE_IDS.get(cle)
            if not sid:
                continue
            row = conn.execute("""
                SELECT COUNT(*) as nb,
                       MAX(collecte_le) as derniere
                FROM articles WHERE source_id = ?
            """, (sid,)).fetchone()
            nb  = row["nb"] if row else 0
            der = (row["derniere"] or "—")[:10] if row else "—"
            print(
                f"{cfg['nom']:<35} {nb:>8} {der:>10}"
            )
        print(f"{'─'*55}\n")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="Scrapers sources internationales IF"
    )
    ap.add_argument(
        "--source",
        nargs="+",
        choices=list(SOURCES_CONFIG.keys()) + ["all"],
        default=["all"],
        help="Source(s) à collecter"
    )
    ap.add_argument("--depuis", metavar="YYYY-MM-DD")
    ap.add_argument("--test",   action="store_true")
    ap.add_argument("--stats",  action="store_true")
    args = ap.parse_args()

    if args.stats:
        init_sources()
        stats()
    elif "all" in args.source:
        scraper_all(
            date_depuis=args.depuis,
            mode_test=args.test
        )
    else:
        init_sources()
        for cle in args.source:
            scraper(cle, args.depuis, args.test)