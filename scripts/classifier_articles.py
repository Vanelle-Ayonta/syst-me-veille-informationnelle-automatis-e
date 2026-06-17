"""
scripts/classifier_articles.py — Backfill de la classification des articles.

Classe chaque article (dimension / zone / cible) par mots-clés via
core.classification, et met à jour les colonnes correspondantes dans
articles. Idempotent : peut être relancé sans risque.

Usage :
  python scripts/classifier_articles.py            # tous les articles non classés
  python scripts/classifier_articles.py --tout     # reclasse TOUT (écrase)
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.classification import classifier_article
from core.database import get_db


def _assurer_colonnes(conn):
    for col in ("dimension", "zone", "cible"):
        try:
            conn.execute(f"ALTER TABLE articles ADD COLUMN {col} TEXT")
        except Exception:
            pass
    try:
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_articles_dimension "
            "ON articles(dimension)"
        )
    except Exception:
        pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill classification articles.")
    parser.add_argument("--tout", action="store_true",
                        help="Reclasse TOUS les articles (sinon : seulement "
                             "ceux dont la dimension est nulle).")
    args = parser.parse_args()

    with get_db() as conn:
        _assurer_colonnes(conn)
        where = "" if args.tout else "WHERE dimension IS NULL"
        rows = conn.execute(
            f"SELECT id, titre, contenu FROM articles {where}"
        ).fetchall()
        total = len(rows)
        print(f"[INFO] {total} article(s) à classer "
              f"({'tous' if args.tout else 'non classés'}).")

        dims, zones, cibles = Counter(), Counter(), Counter()
        maj = 0
        for r in rows:
            c = classifier_article(r["titre"], r["contenu"] or "")
            conn.execute(
                "UPDATE articles SET dimension=?, zone=?, cible=? WHERE id=?",
                (c["dimension"], c["zone"], c["cible"], r["id"]),
            )
            maj += 1
            dims[c["dimension"] or "—"] += 1
            zones[c["zone"] or "—"] += 1
            cibles[c["cible"] or "—"] += 1

    print(f"[OK] {maj} article(s) classés.")
    print("\nPar dimension :")
    for k, v in dims.most_common():
        print(f"  {k:<32} {v}")
    print("\nPar zone :")
    for k, v in zones.most_common():
        print(f"  {k:<32} {v}")
    print("\nPar cible :")
    for k, v in cibles.most_common():
        print(f"  {k:<32} {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
