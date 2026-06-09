"""
scraper_all.py — Orchestrateur central du système de veille DIIF/BEAC
======================================================================
Lance tous les scrapers EN PARALLÈLE (ThreadPoolExecutor, MAX_WORKERS=5)
et produit un rapport de synthèse.

SOURCES COUVERTES (22 sources)
───────────────────────────────
 1. Digital Business Africa      scraper_dba.py
 2. FinDev Gateway               scraper_findev.py
 3. AFI Global                   scraper_afi.py
 4. GSMA                         scraper_gsma.py
 5. CNEF Cameroun                scraper_cnef.py
 6. Banque de France             scraper_bdf.py
 7. BRI                          scraper_bis.py
 8. GIMAC                        scraper_gimac.py
 9. La Finance pour Tous         scraper_lfpt.py
10. Banque du Canada             scraper_playwright_banks.py --source canada
11. Central Bank of Kenya (CBK)  scraper_wp_banks.py --source kenya
12. BCEAO                        scraper_bceao.py
13. Bank Al-Maghrib (BKAM)       scraper_bkam.py
14. Central Bank of Nigeria CBN  scraper_cbn_bnr.py --source cbn
15. National Bank of Rwanda BNR  scraper_cbn_bnr.py --source bnr
16. Banque mondiale              scraper_intl.py --source worldbank
17. CGAP                         scraper_intl.py --source cgap
18. Women's World Banking        scraper_intl.py --source wwb
19. Better Than Cash Alliance    scraper_intl.py --source btca
20. Center for Financial Incl.   scraper_intl.py --source cfi
21. ADA Luxembourg               scraper_intl.py --source ada
22. AFD                          scraper_intl.py --source afd

PARALLÉLISATION
───────────────
MAX_WORKERS = 5 — limite volontaire pour :
  - Respecter les sites sources (pas de surcharge)
  - Éviter les conflits SQLite (WAL + busy_timeout gèrent la contention)
  - La Banque du Canada (Playwright) tourne en parallèle des autres

USAGE
─────
    python scraper_all.py                          # tout collecter
    python scraper_all.py --depuis 2024-01-01      # depuis une date
    python scraper_all.py --test                   # mode test rapide
    python scraper_all.py --source 1 2 3           # sources spécifiques
    python scraper_all.py --stats                  # statistiques uniquement
    python scraper_all.py --nettoyer               # nettoyage texte uniquement
"""

import subprocess
import sys
import time
import sqlite3
import argparse
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

PYTHON = sys.executable

# Nombre maximum de scrapers en parallèle
MAX_WORKERS = 5

COMMANDES = {
    1:  [PYTHON, "scraper_dba.py"],
    2:  [PYTHON, "scraper_findev.py"],
    3:  [PYTHON, "scraper_afi.py"],
    4:  [PYTHON, "scraper_gsma.py"],
    5:  [PYTHON, "scraper_cnef.py"],
    6:  [PYTHON, "scraper_bdf.py"],
    7:  [PYTHON, "scraper_bis.py"],
    8:  [PYTHON, "scraper_gimac.py"],
    9:  [PYTHON, "scraper_lfpt.py"],
    10: [PYTHON, "scraper_playwright_banks.py", "--source", "canada"],
    11: [PYTHON, "scraper_wp_banks.py",         "--source", "kenya"],
    12: [PYTHON, "scraper_bceao.py"],
    13: [PYTHON, "scraper_bkam.py"],
    14: [PYTHON, "scraper_cbn_bnr.py",          "--source", "cbn"],
    15: [PYTHON, "scraper_cbn_bnr.py",          "--source", "bnr"],
    # Sources internationales (scraper_intl.py)
    16: [PYTHON, "scraper_intl.py",             "--source", "worldbank"],
    17: [PYTHON, "scraper_intl.py",             "--source", "cgap"],
    18: [PYTHON, "scraper_intl.py",             "--source", "wwb"],
    19: [PYTHON, "scraper_intl.py",             "--source", "btca"],
    20: [PYTHON, "scraper_intl.py",             "--source", "cfi"],
    21: [PYTHON, "scraper_intl.py",             "--source", "ada"],
    22: [PYTHON, "scraper_intl.py",             "--source", "afd"],
}

BASES = {
    1:  "digitalbusiness_africa.db",
    2:  "findevgateway.db",
    3:  "afi_global.db",
    4:  "gsma.db",
    5:  "cnef_cameroun.db",
    6:  "banque_france.db",
    7:  "bis.db",
    8:  "gimac.db",
    9:  "lafinancepourtous.db",
    10: "banque_canada.db",
    11: "cbk_kenya.db",
    12: "bceao.db",
    13: "bkam.db",
    14: "cbn_nigeria.db",
    15: "bnr_rwanda.db",
    16: "intl_sources.db",
    17: "intl_sources.db",
    18: "intl_sources.db",
    19: "intl_sources.db",
    20: "intl_sources.db",
    21: "intl_sources.db",
    22: "intl_sources.db",
}

NOMS = {
    1:  "Digital Business Africa",
    2:  "FinDev Gateway",
    3:  "AFI Global",
    4:  "GSMA",
    5:  "CNEF Cameroun",
    6:  "Banque de France",
    7:  "BRI",
    8:  "GIMAC",
    9:  "La Finance pour Tous",
    10: "Banque du Canada",
    11: "Central Bank of Kenya",
    12: "BCEAO",
    13: "Bank Al-Maghrib",
    14: "CBN Nigeria",
    15: "BNR Rwanda",
    16: "Banque mondiale",
    17: "CGAP",
    18: "Women's World Banking",
    19: "Better Than Cash Alliance",
    20: "Center for Financial Inclusion",
    21: "ADA Luxembourg",
    22: "AFD",
}

# Timeout par source (secondes) — les sources lentes ont un délai étendu
TIMEOUTS = {
    1:  900,   # Digital Business Africa — RSS + sitemap volumineux
    10: 900,   # Banque du Canada — Playwright (Chrome headless)
    17: 900,   # CGAP — 48+ pages HTML paginées
}
DEFAULT_TIMEOUT = 600

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────
# Lancement d'un scraper individuel (appelé depuis ThreadPoolExecutor)
# ──────────────────────────────────────────────────────────────────

def lancer_scraper(source_id: int, date_depuis: str = None,
                   mode_test: bool = False) -> tuple:
    """
    Lance un scraper en subprocess et capture sa sortie.
    Thread-safe : chaque appel est indépendant (variables locales, subprocess séparé).
    Retourne (ok: bool, duree: float, msg: str).
    """
    cmd = list(COMMANDES[source_id])
    if date_depuis:
        cmd += ["--depuis", date_depuis]
    if mode_test:
        cmd += ["--test"]

    nom     = NOMS[source_id]
    timeout = TIMEOUTS.get(source_id, DEFAULT_TIMEOUT)
    log.info(f"[START] [{source_id:02d}] {nom} (timeout={timeout}s)")

    debut = time.time()
    try:
        result = subprocess.run(
            cmd,
            timeout=timeout,
            cwd=str(Path(__file__).parent),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        duree  = time.time() - debut
        ok     = result.returncode == 0
        # Les scrapers logent via logging → stderr ; stdout peut être vide
        sortie = (result.stderr or "") + (result.stdout or "")

        # Extraire le nombre d'articles collectés depuis la ligne de résumé final.
        # Patterns connus :  "X nouvel(s) article(s)"  (scraper_findev, scraper_afi…)
        #                    "X article(s) collecté(s)" (scraper_intl, scraper_bis…)
        nouveaux = 0
        matches = re.findall(
            r"(\d+)\s+(?:nouvel|article)",
            sortie, re.IGNORECASE
        )
        if matches:
            nouveaux = int(matches[-1])  # dernier nombre = ligne de résumé

        # Log les lignes clés après complétion
        lignes_cles = [
            l.strip() for l in sortie.splitlines()
            if l.strip() and any(tok in l for tok in [
                "article(s) collect", "Collecte termin",
                "nouvel(s) article", "ERREUR", "Exception",
            ])
        ]
        for ligne in lignes_cles[-4:]:
            log.info(f"  [{source_id:02d}] {ligne[:120]}")

        if not ok and result.stderr:
            for ligne in result.stderr.splitlines()[-3:]:
                if ligne.strip():
                    log.warning(f"  [{source_id:02d}] ERR: {ligne.strip()}")

        msg = "Succes" if ok else f"Erreur (code {result.returncode})"
        return ok, duree, msg, nouveaux

    except subprocess.TimeoutExpired:
        duree = time.time() - debut
        log.warning(f"  [{source_id:02d}] {nom} : Timeout ({duree:.0f}s)")
        return False, duree, "Timeout", 0

    except Exception as e:
        duree = time.time() - debut
        log.warning(f"  [{source_id:02d}] {nom} : Exception — {e}")
        return False, duree, str(e), 0


# ──────────────────────────────────────────────────────────────────
# Statistiques depuis la base centrale veille_diif.db
# ──────────────────────────────────────────────────────────────────

def _get_central_db() -> Path:
    """Résout le chemin absolu de veille_diif.db depuis config.py."""
    _root = Path(__file__).parent.parent
    try:
        sys.path.insert(0, str(_root))
        from config import DB_PATH as _cfg
        p = Path(_cfg)
        return p if p.is_absolute() else _root / p
    except Exception:
        return _root / "data" / "veille_diif.db"


def afficher_stats(source_ids=None):
    """Lit les compteurs depuis la base centrale (data/veille_diif.db)."""
    db_path = _get_central_db()
    if not db_path.exists():
        log.warning(f"Base centrale introuvable : {db_path}")
        return

    try:
        conn = sqlite3.connect(str(db_path))
        total_global    = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
        derniere        = conn.execute("SELECT MAX(collecte_le) FROM articles").fetchone()[0]
        par_source      = dict(conn.execute(
            "SELECT s.nom, COUNT(*) FROM articles a "
            "JOIN sources s ON a.source_id = s.id "
            "GROUP BY s.nom"
        ).fetchall())
        conn.close()
    except Exception as e:
        log.warning(f"Erreur lecture stats : {e}")
        return

    ids = sorted(source_ids or list(NOMS.keys()))
    log.info("")
    log.info("=" * 65)
    log.info(f"{'STATISTIQUES veille_diif.db':^65}")
    log.info(f"  Total : {total_global} articles  |  Derniere collecte : {(derniere or 'N/A')[:19]}")
    log.info("=" * 65)
    log.info(f"  {'#':<4} {'Source':<38} {'Articles':>8}")
    log.info("  " + "-" * 54)
    for sid in ids:
        nom   = NOMS[sid]
        count = par_source.get(nom, 0)
        log.info(f"  [{sid:02d}] {nom:<38} {count:>8}")
    log.info("  " + "-" * 54)
    log.info(f"  {'TOTAL GLOBAL':<43} {total_global:>8}")
    log.info("=" * 65)


def lancer_nettoyage(source_ids=None):
    ids = source_ids or list(BASES.keys())
    log.info("-- NETTOYAGE DU TEXTE --")
    for sid in sorted(ids):
        db = BASES[sid]
        if not Path(db).exists():
            log.warning(f"  [{sid}] {NOMS[sid]} : base introuvable")
            continue
        log.info(f"  [{sid}] Nettoyage : {db}")
        try:
            subprocess.run([PYTHON, "cleaner.py", "--db", db], timeout=120,
                           capture_output=True)
        except Exception as e:
            log.warning(f"  [{sid}] Erreur nettoyage : {e}")


# ──────────────────────────────────────────────────────────────────
# Orchestrateur principal — parallélisation par ThreadPoolExecutor
# ──────────────────────────────────────────────────────────────────

def orchestrer(source_ids=None, date_depuis=None, date_debut=None,
               mode_test=False, nettoyer=False):
    """
    Lance tous les scrapers en parallèle (MAX_WORKERS=5).

    Chaque scraper est un subprocess indépendant — pas de GIL, pas de
    partage mémoire. SQLite WAL + busy_timeout gèrent la contention en écriture.

    Retourne : dict {source_id: {"ok": bool, "duree": float, "msg": str}}
    """
    # Résolution du paramètre date
    date_depuis = date_debut or date_depuis
    if date_depuis is None:
        from datetime import date as _date, timedelta
        date_depuis = (_date.today() - timedelta(days=30)).strftime("%Y-%m-%d")

    ids = sorted(source_ids or list(COMMANDES.keys()))

    log.info("=" * 60)
    log.info("SYSTEME DE VEILLE DIIF/BEAC — DEMARRAGE PARALLELE")
    log.info(f"Sources : {len(ids)} | Workers max : {MAX_WORKERS} | Depuis : {date_depuis} | Test : {mode_test}")
    log.info("=" * 60)

    debut_global = time.time()
    resultats: dict = {}

    # ── Exécution parallèle ──────────────────────────────────────
    with ThreadPoolExecutor(max_workers=MAX_WORKERS,
                             thread_name_prefix="scraper") as executor:
        futures = {
            executor.submit(lancer_scraper, sid, date_depuis, mode_test): sid
            for sid in ids
        }

        termine = 0
        for future in as_completed(futures):
            sid = futures[future]
            nom = NOMS[sid]
            termine += 1
            try:
                ok, duree, msg, nouveaux = future.result()
                resultats[sid] = {"ok": ok, "duree": duree, "msg": msg, "nouveaux": nouveaux}
                statut = "OK  " if ok else "ERREUR"
                log.info(
                    f"[{termine:02d}/{len(ids)} DONE] [{sid:02d}] {nom:<30} "
                    f"{statut} (+{nouveaux}) ({duree:.0f}s)"
                )
            except Exception as e:
                resultats[sid] = {"ok": False, "duree": 0.0, "msg": str(e), "nouveaux": 0}
                log.warning(
                    f"[{termine:02d}/{len(ids)} DONE] [{sid:02d}] {nom} : "
                    f"EXCEPTION — {e}"
                )

    duree_totale = time.time() - debut_global

    if nettoyer:
        lancer_nettoyage(ids)

    # ── Rapport final ──────────────────────────────────────────────
    succes         = sum(1 for r in resultats.values() if r["ok"])
    echecs         = len(resultats) - succes
    total_nouveaux = sum(r.get("nouveaux", 0) for r in resultats.values())

    log.info("")
    log.info("=" * 65)
    log.info(f"{'RAPPORT DE COLLECTE':^65}")
    log.info("=" * 65)
    log.info(f"  {'#':<4} {'Source':<32} {'Statut':<8} {'Nvx':>4} {'Duree':>6}")
    log.info("  " + "-" * 63)

    for sid in sorted(resultats):
        r      = resultats[sid]
        statut = "OK" if r["ok"] else "ERREUR"
        log.info(
            f"  [{sid:02d}] {NOMS[sid]:<32} {statut:<8} {r.get('nouveaux',0):>4} {r['duree']:>5.0f}s"
        )

    log.info("  " + "-" * 63)
    log.info(
        f"  Succes : {succes}/{len(resultats)} | "
        f"Nouveaux : {total_nouveaux} | "
        f"Duree totale : {duree_totale:.0f}s"
    )
    log.info("=" * 65)

    if echecs > 0:
        log.warning(f"\n  {echecs} scraper(s) en erreur :")
        for sid in sorted(resultats):
            if not resultats[sid]["ok"]:
                log.warning(
                    f"    [{sid:02d}] {NOMS[sid]} — {resultats[sid]['msg']}"
                )

    afficher_stats(ids)

    return {
        "ok":             echecs == 0,
        "succes":         succes,
        "erreurs":        echecs,
        "nouveaux":       total_nouveaux,
        "duree_totale":   int(duree_totale),
        "sources": {
            NOMS[sid]: {
                "statut":   "OK" if resultats[sid]["ok"] else "ERREUR",
                "nouveaux": resultats[sid].get("nouveaux", 0),
                "duree":    int(resultats[sid]["duree"]),
                "message":  resultats[sid]["msg"],
            }
            for sid in sorted(resultats)
        },
    }


# ──────────────────────────────────────────────────────────────────
# Point d'entrée CLI
# ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="Orchestrateur de veille DIIF/BEAC (parallele, MAX_WORKERS=5)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemples :
  python scraper_all.py                          # tout collecter (30j par defaut)
  python scraper_all.py --depuis 2024-01-01
  python scraper_all.py --test
  python scraper_all.py --source 1 2 12
  python scraper_all.py --stats
  python scraper_all.py --nettoyer
        """
    )
    ap.add_argument("--depuis",   metavar="YYYY-MM-DD",
                    help="Date de debut (defaut : aujourd'hui - 30j)")
    ap.add_argument("--test",     action="store_true",
                    help="Mode test : 1 page par scraper")
    ap.add_argument("--source",   nargs="+", type=int,
                    choices=list(COMMANDES.keys()), metavar="ID",
                    help="IDs de sources specifiques (1-22)")
    ap.add_argument("--stats",    action="store_true",
                    help="Afficher les statistiques uniquement")
    ap.add_argument("--nettoyer", action="store_true",
                    help="Nettoyer le texte apres collecte")
    ap.add_argument("--workers",  type=int, default=MAX_WORKERS,
                    metavar="N",
                    help=f"Nombre de workers paralleles (defaut : {MAX_WORKERS})")
    args = ap.parse_args()

    # Override MAX_WORKERS si spécifié en CLI
    if args.workers != MAX_WORKERS:
        MAX_WORKERS = max(1, min(args.workers, 10))
        log.info(f"Workers : {MAX_WORKERS} (override CLI)")

    if args.stats:
        afficher_stats(args.source)
    elif args.nettoyer and not args.source and not args.depuis and not args.test:
        lancer_nettoyage(args.source)
    else:
        orchestrer(
            source_ids=args.source,
            date_depuis=args.depuis,
            mode_test=args.test,
            nettoyer=args.nettoyer,
        )
