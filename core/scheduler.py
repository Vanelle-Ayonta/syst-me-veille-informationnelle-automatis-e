"""
core/scheduler.py — Planificateur de collecte automatique
Lance le scraping à intervalle configurable.
"""
import threading
import time
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import SCRAPING_INTERVAL_HOURS

_scheduler_thread = None
_stop_event       = threading.Event()


def _boucle_collecte():
    import subprocess
    import sys as _sys
    import os as _os
    _script = _os.path.join(
        _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
        "scrapers", "scraper_all.py",
    )
    intervalle = SCRAPING_INTERVAL_HOURS * 3600
    # Attendre un cycle complet avant la première collecte automatique.
    # Évite le déclenchement immédiat si le planificateur est démarré par accident.
    print(f"[SCHEDULER] Première collecte dans {SCRAPING_INTERVAL_HOURS}h.")
    _stop_event.wait(intervalle)
    while not _stop_event.is_set():
        print("[SCHEDULER] Lancement collecte automatique...")
        try:
            subprocess.run([_sys.executable, _script], check=False)
            print("[SCHEDULER] Terminé.")
        except Exception as e:
            print(f"[SCHEDULER] Erreur : {e}")
        _stop_event.wait(intervalle)


def demarrer_scheduler():
    global _scheduler_thread, _stop_event
    if _scheduler_thread and _scheduler_thread.is_alive():
        return  # Déjà en cours
    _stop_event = threading.Event()
    _scheduler_thread = threading.Thread(
        target=_boucle_collecte, daemon=True, name="CollecteScheduler"
    )
    _scheduler_thread.start()
    print(f"[SCHEDULER] Démarré — intervalle : {SCRAPING_INTERVAL_HOURS}h")


def arreter_scheduler():
    global _stop_event
    _stop_event.set()
    print("[SCHEDULER] Arrêté.")


def scheduler_actif() -> bool:
    return _scheduler_thread is not None and _scheduler_thread.is_alive()
