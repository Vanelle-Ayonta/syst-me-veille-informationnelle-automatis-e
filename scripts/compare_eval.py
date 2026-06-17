"""
scripts/compare_eval.py — Tableau comparatif avant/après améliorations.

Compare deux (ou plusieurs) fichiers d'évaluation JSON produits par
eval_retrieval.py ou eval_agentique.py et génère :
  - Un tableau console lisible
  - Un fichier CSV exportable (pour Word, Excel, LaTeX)
  - Un résumé texte pour le mémoire

Détecte automatiquement le type d'évaluation (retrieval ou agentique).

Usage :
  # Comparer deux evals agentiques (avant / après)
  python scripts/compare_eval.py \\
      results/agentic_eval_20260615_183251.json \\
      results/agentic_eval_20260616_225909.json \\
      --labels "Avant (baseline)" "Après (Étapes 1-3)"

  # Comparer retrieval FAISS seul vs FAISS + reranker
  python scripts/compare_eval.py \\
      results/retrieval_eval_AVANT.json \\
      results/retrieval_eval_APRES.json \\
      --labels "FAISS seul" "FAISS + Cross-encoder"

  # Auto : le script devine les labels depuis la date des fichiers
  python scripts/compare_eval.py results/agentic_eval_A.json results/agentic_eval_B.json
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import datetime

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

RESULTS_DIR = os.path.join(_ROOT, "results")


# ── Noms lisibles des métriques ────────────────────────────────────────────────

NOMS_METRIQUES = {
    # Agentique — trajectoire
    "search_corpus_appele": "Outil recherche appelé",
    "reformulation":        "Reformulation détectée",
    "nb_recherches":        "Nb recherches (moy.)",
    "sources_non_vides":    "Sources non vides",
    # Agentique — génération
    "faithfulness":         "Fidélité (faithfulness)",
    "answer_relevancy":     "Pertinence réponse",
    "context_relevance":    "Pertinence contexte",
    "qualite_globale":      "Qualité globale",
    "answer_similarity":    "Similarité référence",
    # Retrieval — niveau chunk
    "precision@5":  "Precision@5 (chunk)",
    "recall@5":     "Recall@5 (chunk)",
    "f1@5":         "F1@5 (chunk)",
    "ndcg@5":       "NDCG@5 (chunk)",
    "precision@8":  "Precision@8 (chunk)",
    "recall@8":     "Recall@8 (chunk)",
    "f1@8":         "F1@8 (chunk)",
    "ndcg@8":       "NDCG@8 (chunk)",
    "precision@10": "Precision@10 (chunk)",
    "recall@10":    "Recall@10 (chunk)",
    "f1@10":        "F1@10 (chunk)",
    "ndcg@10":      "NDCG@10 (chunk)",
    "mrr":          "MRR (chunk)",
    "hit_rate@5":   "Hit Rate@5 (chunk)",
    "hit_rate@8":   "Hit Rate@8 (chunk)",
    "hit_rate@10":  "Hit Rate@10 (chunk)",
    # Retrieval — niveau article (robuste à la déduplication)
    "article_hit@5":       "Hit Rate@5 (article)",
    "article_hit@8":       "Hit Rate@8 (article)",
    "article_hit@10":      "Hit Rate@10 (article)",
    "article_precision@5": "Precision@5 (article)",
    "article_precision@8": "Precision@8 (article)",
    "article_precision@10":"Precision@10 (article)",
    "article_recall@5":    "Recall@5 (article)",
    "article_recall@8":    "Recall@8 (article)",
    "article_recall@10":   "Recall@10 (article)",
    "mrr_article":         "MRR (article)",
    "article_hit_rate@5":  "Hit Rate@5 (article, global)",
    "article_hit_rate@8":  "Hit Rate@8 (article, global)",
    "article_hit_rate@10": "Hit Rate@10 (article, global)",
}

# Groupes pour affichage structuré
GROUPES_AGENTIQUE = [
    ("Comportement agentique (sans LLM)",
     ["search_corpus_appele", "reformulation", "nb_recherches", "sources_non_vides"]),
    ("Qualité de génération (juge LLM)",
     ["faithfulness", "answer_relevancy", "context_relevance",
      "qualite_globale", "answer_similarity"]),
]

GROUPES_RETRIEVAL = [
    ("Niveau CHUNK @k=5",    ["precision@5",  "recall@5",  "f1@5",  "ndcg@5"]),
    ("Niveau CHUNK @k=8",    ["precision@8",  "recall@8",  "f1@8",  "ndcg@8"]),
    ("Niveau CHUNK @k=10",   ["precision@10", "recall@10", "f1@10", "ndcg@10"]),
    ("Niveau ARTICLE @k=5",  ["article_hit@5",  "article_precision@5",  "article_recall@5"]),
    ("Niveau ARTICLE @k=8",  ["article_hit@8",  "article_precision@8",  "article_recall@8"]),
    ("Niveau ARTICLE @k=10", ["article_hit@10", "article_precision@10", "article_recall@10"]),
    ("Synthèse",             ["mrr", "mrr_article",
                               "hit_rate@8", "article_hit_rate@8",
                               "hit_rate@10", "article_hit_rate@10"]),
]


# ── Chargement ─────────────────────────────────────────────────────────────────

def charger_eval(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def extraire_moyennes(data: dict) -> dict:
    """Extrait le dict de moyennes selon le type de fichier."""
    eval_type = data.get("type", "")
    if eval_type == "retrieval":
        return data.get("moyennes", {})
    elif eval_type == "agentique":
        return data.get("rapport", {}).get("averages", {})
    # Fallback : chercher un dict 'averages' ou 'moyennes'
    return data.get("averages", data.get("moyennes", {}))


def extraire_meta(data: dict, path: str) -> dict:
    """Extrait les métadonnées utiles pour l'affichage."""
    return {
        "type":     data.get("type", "inconnu"),
        "date":     data.get("date", "")[:16],
        "n":        data.get("n_cas", data.get("n_questions", "?")),
        "source":   data.get("source", data.get("pipeline", "")),
        "fichier":  os.path.basename(path),
    }


# ── Calcul des deltas ──────────────────────────────────────────────────────────

def delta(avant: float | None, apres: float | None) -> tuple[float | None, float | None]:
    """
    Retourne (delta_absolu, delta_relatif_pct).
    delta_relatif = ((après - avant) / avant) × 100, ou None si avant = 0.
    """
    if avant is None or apres is None:
        return None, None
    d_abs = apres - avant
    d_rel = (d_abs / avant * 100) if avant != 0 else None
    return d_abs, d_rel


def signe(v: float) -> str:
    return "+" if v >= 0 else ""


# ── Affichage console ──────────────────────────────────────────────────────────

def afficher_tableau(
    labels: list[str],
    moyennes_list: list[dict],
    eval_type: str,
    metas: list[dict],
):
    groupes = GROUPES_AGENTIQUE if eval_type == "agentique" else GROUPES_RETRIEVAL

    # En-tête
    print()
    print("═" * 78)
    titre = "AGENTIQUE" if eval_type == "agentique" else "RETRIEVAL"
    print(f"  COMPARAISON {titre} — {len(labels)} version(s)")
    for i, (lbl, meta) in enumerate(zip(labels, metas)):
        print(f"  [{i+1}] {lbl}  (n={meta['n']}, {meta['date']}, {meta['source']})")
    print("═" * 78)

    # Colonnes : Métrique | val1 | val2 | Δ abs | Δ %
    col_w = [32] + [10] * len(labels)
    if len(labels) == 2:
        col_w += [10, 10]

    def ligne_sep():
        print("─" * 78)

    def cellule(v, width=10):
        if v is None:
            return "  —".ljust(width)
        if isinstance(v, float):
            return f"  {v:.4f}".ljust(width)
        return f"  {v}".ljust(width)

    for nom_groupe, metriques in groupes:
        # Vérifier si au moins une métrique du groupe est disponible
        disponibles = [m for m in metriques if any(m in mx for mx in moyennes_list)]
        if not disponibles:
            continue

        print(f"\n  ▸ {nom_groupe}")
        ligne_sep()

        # En-têtes colonnes
        entete = "  Métrique".ljust(col_w[0])
        for i, lbl in enumerate(labels):
            entete += lbl[:col_w[i+1]-2].center(col_w[i+1])
        if len(labels) == 2:
            entete += "  Δ abs".ljust(col_w[-2])
            entete += "  Δ %".ljust(col_w[-1])
        print(entete)
        ligne_sep()

        for metrique in disponibles:
            nom = NOMS_METRIQUES.get(metrique, metrique)
            vals = [mx.get(metrique) for mx in moyennes_list]

            ligne = f"  {nom[:col_w[0]-4]}".ljust(col_w[0])
            for v in vals:
                ligne += cellule(v, col_w[1])

            if len(labels) == 2 and vals[0] is not None and vals[1] is not None:
                d_abs, d_rel = delta(vals[0], vals[1])
                sn = signe(d_abs)
                ligne += f"  {sn}{d_abs:.4f}".ljust(col_w[-2])
                if d_rel is not None:
                    ligne += f"  {sn}{d_rel:.1f}%".ljust(col_w[-1])
                else:
                    ligne += "  —".ljust(col_w[-1])
            print(ligne)

        ligne_sep()

    print()


# ── Export CSV ─────────────────────────────────────────────────────────────────

def exporter_csv(
    labels: list[str],
    moyennes_list: list[dict],
    eval_type: str,
    metas: list[dict],
    chemin: str,
):
    groupes = GROUPES_AGENTIQUE if eval_type == "agentique" else GROUPES_RETRIEVAL

    rows = []
    for nom_groupe, metriques in groupes:
        for metrique in metriques:
            vals = [mx.get(metrique) for mx in moyennes_list]
            if all(v is None for v in vals):
                continue
            row = {
                "Groupe":   nom_groupe,
                "Métrique": NOMS_METRIQUES.get(metrique, metrique),
                "Clé":      metrique,
            }
            for lbl, v in zip(labels, vals):
                row[lbl] = f"{v:.4f}" if v is not None else ""
            if len(labels) == 2 and vals[0] is not None and vals[1] is not None:
                d_abs, d_rel = delta(vals[0], vals[1])
                row["Δ absolu"] = f"{signe(d_abs)}{d_abs:.4f}"
                row["Δ %"] = f"{signe(d_rel)}{d_rel:.1f}%" if d_rel is not None else "—"
            rows.append(row)

    if not rows:
        return

    fieldnames = list(rows[0].keys())
    with open(chemin, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


# ── Résumé narratif ────────────────────────────────────────────────────────────

def generer_resume(
    labels: list[str],
    moyennes_list: list[dict],
    eval_type: str,
    metas: list[dict],
) -> str:
    """Génère un résumé textuel synthétique pour le mémoire."""
    if len(labels) != 2:
        return ""

    avant, apres = moyennes_list[0], moyennes_list[1]
    lignes = [
        f"Résumé comparatif — {eval_type.upper()}",
        f"{'─' * 50}",
        f"Avant : {labels[0]}  (n={metas[0]['n']}, {metas[0]['date']})",
        f"Après : {labels[1]}  (n={metas[1]['n']}, {metas[1]['date']})",
        "",
    ]

    # Trouver les métriques améliorées / dégradées
    ameliorations = []
    degradations  = []

    cles_pertinentes = (
        ["search_corpus_appele", "faithfulness", "answer_relevancy",
         "context_relevance", "qualite_globale", "answer_similarity"]
        if eval_type == "agentique"
        else ["precision@8", "recall@8", "ndcg@8", "mrr"]
    )

    for cle in cles_pertinentes:
        v_av = avant.get(cle)
        v_ap = apres.get(cle)
        if v_av is None or v_ap is None:
            continue
        d_abs, d_rel = delta(v_av, v_ap)
        nom = NOMS_METRIQUES.get(cle, cle)
        if d_abs > 0.01:
            ameliorations.append(
                f"  {nom} : {v_av:.4f} → {v_ap:.4f} "
                f"({signe(d_abs)}{d_abs:.4f}, "
                f"{('+' if d_rel>=0 else '')}{d_rel:.1f}%)"
            )
        elif d_abs < -0.01:
            degradations.append(
                f"  {nom} : {v_av:.4f} → {v_ap:.4f} "
                f"({d_abs:.4f}, {d_rel:.1f}%)"
            )

    if ameliorations:
        lignes.append("Améliorations :")
        lignes.extend(ameliorations)
    if degradations:
        lignes.append("\nDégradations :")
        lignes.extend(degradations)
    if not ameliorations and not degradations:
        lignes.append("Aucune variation significative (> 0.01) détectée.")

    return "\n".join(lignes)


# ── Point d'entrée ─────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Tableau comparatif avant/après évaluation SVIA."
    )
    parser.add_argument(
        "fichiers", nargs="+",
        help="Fichiers JSON d'évaluation à comparer (dans l'ordre : avant, après, …)."
    )
    parser.add_argument(
        "--labels", nargs="*", default=None,
        help="Labels pour chaque fichier (même ordre). Ex: --labels 'Avant' 'Après'."
    )
    parser.add_argument(
        "--no-csv", action="store_true",
        help="Ne pas exporter le CSV."
    )
    args = parser.parse_args()

    # ── Résoudre les chemins (relatif à _ROOT si le fichier n'existe pas tel quel)
    chemins = []
    for p in args.fichiers:
        if os.path.exists(p):
            chemins.append(p)
        else:
            candidate = os.path.join(RESULTS_DIR, p)
            if os.path.exists(candidate):
                chemins.append(candidate)
            else:
                print(f"[ERREUR] Fichier introuvable : {p}")
                return 1

    # ── Labels
    labels = args.labels or [f"Version {i+1}" for i in range(len(chemins))]
    if len(labels) < len(chemins):
        labels += [f"Version {i+1}" for i in range(len(labels), len(chemins))]

    # ── Chargement
    donnees = [charger_eval(p) for p in chemins]
    metas   = [extraire_meta(d, p) for d, p in zip(donnees, chemins)]
    moys    = [extraire_moyennes(d) for d in donnees]

    # ── Détection du type (prend le type du premier fichier)
    eval_type = donnees[0].get("type", "agentique")

    # ── Affichage
    afficher_tableau(labels, moys, eval_type, metas)

    # ── Résumé
    resume = generer_resume(labels, moys, eval_type, metas)
    if resume:
        print(resume)
        print()

    # ── Export CSV
    if not args.no_csv:
        os.makedirs(RESULTS_DIR, exist_ok=True)
        horodatage = datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_path = os.path.join(RESULTS_DIR, f"comparaison_{eval_type}_{horodatage}.csv")
        exporter_csv(labels, moys, eval_type, metas, csv_path)
        print(f"[OK] CSV exporté : {os.path.relpath(csv_path, _ROOT)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
