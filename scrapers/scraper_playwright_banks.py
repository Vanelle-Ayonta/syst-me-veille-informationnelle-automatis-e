"""
scraper_playwright_banks.py — Scraper Playwright pour sites protégés par WAF
=============================================================================
Couvre :
  - Banque du Canada  (bankofcanada.ca) — bloqué par WAF via requests
  - Bank of Ghana     (bog.gov.gh)      — bloqué par WAF via requests

Playwright pilote un vrai navigateur Chrome installé sur la machine,
ce qui contourne les protections WAF qui bloquent les requêtes automatisées
depuis des serveurs.

PRÉREQUIS
─────────
    pip install playwright
    playwright install chromium

USAGE
─────
    python scraper_playwright_banks.py --source all --test
    python scraper_playwright_banks.py --source canada --test
    python scraper_playwright_banks.py --source ghana --test
    python scraper_playwright_banks.py --source all --depuis 2023-01-01
    python scraper_playwright_banks.py --stats

NOTE : Ce script doit être exécuté depuis un poste avec Chrome installé.
       Il ne fonctionnera pas depuis un serveur sans interface graphique
       (sauf en mode headless, ce qui peut être de nouveau bloqué).
"""

import sqlite3
import time
import argparse
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
    PLAYWRIGHT_OK = True
except ImportError:
    PLAYWRIGHT_OK = False
    print("ERREUR : Playwright non installé. Exécuter : pip install playwright && playwright install chromium")

from bs4 import BeautifulSoup

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from base_scraper import get_or_create_source, url_existe, sauvegarder_article

SOURCE_IDS = {
    "canada": get_or_create_source("Banque du Canada", "https://www.bankofcanada.ca", "en", "web"),
    "ghana":  get_or_create_source("Bank of Ghana", "https://www.bog.gov.gh", "en", "web"),
}

# ─────────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────────

SOURCES = {
    "canada": {
        "nom":      "Banque du Canada",
        "base_url": "https://www.bankofcanada.ca",
        "db":       "banque_canada.db",
        "langue":   "en",
        "source":   "Bank of Canada",
        "filtrer":  True,
        # Pages de liste à parcourir
        "listes": [
            {
                "url": "https://www.bankofcanada.ca/research/browse/",
                "selector_articles": "article a, h2 a, h3 a, .entry-title a",
                "selector_next": "a.next, .nav-next a, [rel='next']",
            },
            {
                "url": "https://www.bankofcanada.ca/publications/",
                "selector_articles": "article a, h2 a, h3 a",
                "selector_next": "a.next, .nav-next a",
            },
        ],
        "prefixes_valides": ["/20", "/research/", "/publications/"],
        "selecteurs_date": [
            "meta[property='article:published_time']",
            "time[datetime]",
            ".entry-date",
            ".published",
        ],
    },
    "ghana": {
        "nom":      "Bank of Ghana",
        "base_url": "https://www.bog.gov.gh",
        "db":       "bog_ghana.db",
        "langue":   "en",
        "source":   "Bank of Ghana",
        "filtrer":  True,
        "listes": [
            {
                "url": "https://www.bog.gov.gh/all-news-page/",
                "selector_articles": "article a, h2 a, h3 a, .entry-title a",
                "selector_next": "a.next, .nav-next a, [rel='next']",
            },
            {
                "url": "https://www.bog.gov.gh/press-release/",
                "selector_articles": "article a, h2 a, h3 a",
                "selector_next": "a.next, .nav-next a",
            },
            {
                "url": "https://www.bog.gov.gh/fintech-innovation/",
                "selector_articles": "article a, h2 a, h3 a",
                "selector_next": "a.next, .nav-next a",
            },
        ],
        "prefixes_valides": ["/news/", "/press-release/", "/fintech-innovation/", "/all-news-page/"],
        "selecteurs_date": [
            "meta[property='article:published_time']",
            "time[datetime]",
            ".entry-date",
            ".published",
        ],
    },
}

# Mots-clés filtre thématique (même liste que scraper_wp_banks.py)
MOTS_CLES = [
    # Inclusion financière
    "financial inclusion", "inclusion financière", "unbanked", "underbanked",
    "bancarisation", "microfinance", "microcredit", "microcrédit",
    "financial access", "access to finance", "mobile money", "mobile banking",
    "agent banking",
    # Innovation / Fintech / Paiements
    "fintech", "digital payment", "paiement numérique",
    "digital finance", "digital currency", "monnaie numérique",
    "cbdc", "central bank digital", "e-money", "open banking", "open finance",
    "interoperability", "fast payment", "instant payment", "remittance",
    "payment system", "payment innovation", "retail payment",
    "cryptocurrency", "stablecoin", "blockchain",
    # Éducation financière
    "financial education", "éducation financière", "financial literacy",
    "financial capability", "financial wellbeing",
    # Stabilité et accès financier
    "financial stability", "financial system", "financial sector",
    "household finance", "consumer finance", "financial vulnerability",
    "low-income", "vulnerable", "underserved",
    # Géographie pertinente
    "africa", "afrique", "sub-saharan", "developing", "emerging market",
    "global south", "least developed",
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────
# UTILITAIRES
# ─────────────────────────────────────────────────────────────────

def parser_date_iso(iso_string):
    if not iso_string:
        return None, None, None, None
    try:
        if "+" not in iso_string and "Z" not in iso_string and "T" in iso_string:
            iso_string += "+00:00"
        dt = datetime.fromisoformat(iso_string).astimezone(timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M:%S"), dt.year, dt.month, dt.day
    except Exception:
        return None, None, None, None


def parser_date_url(url):
    m = re.search(r'/(\d{4})/(\d{2})/(\d{2})/', url)
    if m:
        a, mo, j = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return f"{a:04d}-{mo:02d}-{j:02d} 00:00:00", a, mo, j
    m = re.search(r'/(\d{4})/(\d{2})/', url)
    if m:
        a, mo = int(m.group(1)), int(m.group(2))
        return f"{a:04d}-{mo:02d}-01 00:00:00", a, mo, 1
    return None, None, None, None


def est_pertinent(titre, resume, filtrer=True):
    if not filtrer:
        return True
    texte = f"{titre} {resume}".lower()
    return any(mot in texte for mot in MOTS_CLES)


def is_article_url(url, config):
    if not url.startswith(config["base_url"]):
        return False
    chemin = url.replace(config["base_url"], "")
    if any(chemin.startswith(p) for p in config["prefixes_valides"]):
        return len(chemin.strip("/")) > 10
    return False


# ─────────────────────────────────────────────────────────────────
# EXTRACTION D'UN ARTICLE VIA PLAYWRIGHT
# ─────────────────────────────────────────────────────────────────

def extraire_article_playwright(page, url, config):
    """
    Navigue vers l'URL et extrait le contenu de l'article.
    Retourne un dict ou None.
    """
    try:
        page.goto(url, wait_until="networkidle", timeout=25000)
        page.wait_for_timeout(2000)  # laisser le JS finir de rendre
    except PlaywrightTimeout:
        log.warning(f"  Timeout navigation : {url[-60:]}")
        return None
    except Exception as e:
        log.warning(f"  Erreur navigation [{url[-60:]}] : {e}")
        return None

    html = page.content()
    soup = BeautifulSoup(html, "html.parser")

    # Titre
    titre = None
    og = soup.find("meta", property="og:title")
    if og:
        titre = og.get("content", "")
        for suffix in [" - Bank of Canada", " - Banque du Canada", " – Bank of Ghana", " - Bank of Ghana"]:
            titre = titre.replace(suffix, "")
        titre = titre.strip()
    if not titre:
        h1 = soup.find("h1")
        titre = h1.get_text(strip=True) if h1 else None

    # Date — chercher dans plusieurs sources par ordre de fiabilité
    date_pub = annee = mois = jour = None

    # 1. JSON-LD schema.org (Banque du Canada et sites gouvernementaux modernes)
    import json as _json
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = _json.loads(script.string or "")
            # Gérer les listes et les objets imbriqués
            items = data if isinstance(data, list) else [data]
            for item in items:
                for key in ["datePublished", "dateCreated", "dateModified"]:
                    val = item.get(key, "")
                    if val:
                        date_pub, annee, mois, jour = parser_date_iso(val)
                        if date_pub:
                            break
                if date_pub:
                    break
        except Exception:
            pass
        if date_pub:
            break

    # 2. Meta tags classiques
    if not date_pub:
        for sel in config["selecteurs_date"]:
            el = soup.select_one(sel)
            if el:
                val = el.get("content", "") or el.get("datetime", "") or el.get_text(strip=True)
                if val:
                    date_pub, annee, mois, jour = parser_date_iso(val)
                    if date_pub:
                        break

    # 3. Fallback URL WordPress /YYYY/MM/DD/
    if not date_pub:
        date_pub, annee, mois, jour = parser_date_url(url)

    # Résumé
    resume = None
    m = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", property="og:description")
    if m:
        resume = m.get("content", "").strip()

    # Contenu
    contenu = ""
    corps = (
        soup.find("div", class_=re.compile(r"entry-content|post-content|article-content"))
        or soup.find("article") or soup.find("main")
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
        "type_contenu": "article",
        "langue": config["langue"],
        "resume": resume,
        "contenu": contenu,
        "source": config["source"],
        "methode_collecte": "playwright",
        "date_scraping": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
    }


# ─────────────────────────────────────────────────────────────────
# COLLECTE VIA PLAYWRIGHT
# ─────────────────────────────────────────────────────────────────

def collecter_playwright(source_key, date_depuis=None, mode_test=False):
    if not PLAYWRIGHT_OK:
        log.warning(
            f"[{source_key}] Playwright non installe — source desactivee temporairement. "
            "Pour activer : pip install playwright && playwright install chromium"
        )
        return 0

    config = SOURCES[source_key]
    source_id = SOURCE_IDS[source_key]

    date_limite = None
    if date_depuis:
        date_limite = datetime.strptime(date_depuis, "%Y-%m-%d").replace(tzinfo=timezone.utc)

    total = 0

    with sync_playwright() as pw:
        # Lancer Chrome en mode headless (serveur) ou visible si PLAYWRIGHT_VISIBLE=1
        import os as _os
        _headless = _os.environ.get("PLAYWRIGHT_VISIBLE") != "1"
        try:
            browser = pw.chromium.launch(
                headless=_headless,
                slow_mo=300 if not _headless else 0,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-web-security",
                ],
            )
        except Exception as _e:
            log.error(
                f"[{source_key}] Chromium inaccessible : {_e}\n"
                "  Executer : playwright install chromium"
            )
            return 0
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="en-US",
            timezone_id="Africa/Accra",
            # Masquer les indices d'automation
            java_script_enabled=True,
        )
        # Masquer navigator.webdriver
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
            Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
        """)
        page = context.new_page()

        for liste_config in config["listes"]:
            url_liste = liste_config["url"]
            log.info(f"\n  Liste : {url_liste}")
            page_num = 1

            while True:
                log.info(f"  Page {page_num} : {url_liste}")
                try:
                    page.goto(url_liste, wait_until="domcontentloaded", timeout=20000)
                    page.wait_for_timeout(1500)
                except Exception as e:
                    log.warning(f"  Erreur chargement liste : {e}")
                    break

                # Extraire les URLs d'articles
                html = page.content()
                soup = BeautifulSoup(html, "html.parser")
                urls_articles = []
                for a in soup.find_all("a", href=True):
                    href = a["href"]
                    if not href.startswith("http"):
                        href = config["base_url"] + href if href.startswith("/") else None
                    if href and is_article_url(href, config) and href not in urls_articles:
                        urls_articles.append(href)

                # Mode debug : sauvegarder HTML et screenshot pour diagnostic
                import os
                if os.environ.get('DEBUG_PLAYWRIGHT'):
                    debug_file = f"debug_{source_key}_page{page_num}.html"
                    with open(debug_file, 'w', encoding='utf-8') as _f:
                        _f.write(html)
                    page.screenshot(path=f"debug_{source_key}_page{page_num}.png")
                    log.info(f"  DEBUG : HTML sauvegardé dans {debug_file} ({len(html)} car)")

                log.info(f"  {len(urls_articles)} article(s) trouvé(s)")
                if not urls_articles:
                    break

                stop = False
                for url_art in urls_articles:
                    if url_existe(url_art):
                        continue

                    article = extraire_article_playwright(page, url_art, config)
                    if article is None:
                        continue

                    if not est_pertinent(article["titre"] or "", article["resume"] or "", config["filtrer"]):
                        continue

                    if date_limite and article["date_publication"]:
                        dt = datetime.strptime(article["date_publication"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                        if dt < date_limite:
                            log.info(f"  ↩ Trop ancien ({article['date_publication']}) — arrêt")
                            stop = True
                            break

                    sauvegarder_article(source_id, article)
                    total += 1
                    log.info(f"  ✓ {(article['titre'] or '')[:65]} | {article['date_publication']}")
                    time.sleep(1.5)

                    if mode_test and total >= 5:
                        stop = True
                        break

                if stop or mode_test:
                    break

                # Page suivante
                next_sel = liste_config.get("selector_next", "a.next")
                next_btn = page.query_selector(next_sel)
                if not next_btn:
                    log.info("  Dernière page atteinte")
                    break

                next_url = next_btn.get_attribute("href")
                if not next_url:
                    break
                if not next_url.startswith("http"):
                    next_url = config["base_url"] + next_url
                url_liste = next_url
                page_num += 1
                time.sleep(1.0)

            if mode_test and total >= 5:
                break

        browser.close()

    log.info(f"\n{'='*55}")
    log.info(f"[{config['nom']}] Collecte terminée — {total} article(s)")
    return total


# ─────────────────────────────────────────────────────────────────
# POINT D'ENTRÉE CLI
# ─────────────────────────────────────────────────────────────────

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


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Scraper Playwright — Banque du Canada & Bank of Ghana")
    ap.add_argument("--source",  nargs="+", choices=list(SOURCES.keys()) + ["all"], default=["all"])
    ap.add_argument("--depuis",  metavar="YYYY-MM-DD")
    ap.add_argument("--test",    action="store_true", help="5 articles max par source")
    ap.add_argument("--stats",   action="store_true")
    args = ap.parse_args()

    if args.stats:
        for key in SOURCES:
            stats_db(key)
    else:
        sources = list(SOURCES.keys()) if "all" in args.source else args.source
        total = 0
        for key in sources:
            n = collecter_playwright(key, date_depuis=args.depuis, mode_test=args.test)
            total += n
        log.info(f"\nTotal général : {total} article(s)")
