"""
scripts/eval_retrieval.py — Évaluation du retrieval (Niveau 1 / 3 niveaux).

Mesure la qualité du pipeline de récupération (FAISS + reranker cross-encoder)
sur le jeu de test annoté (results/testset.json) généré via generate_testset.py.

Métriques calculées pour chaque valeur de k :
  - Precision@k   : fraction des k chunks récupérés qui figurent dans le ground truth
  - Recall@k      : fraction des chunks ground truth effectivement récupérés parmi les k
  - F1@k          : moyenne harmonique Precision@k / Recall@k
  - NDCG@k        : Normalized Discounted Cumulative Gain — récompense les documents
                    pertinents situés en haut du classement
  - MRR           : Mean Reciprocal Rank — position du 1er document pertinent

Aucun appel LLM — évaluation purement déterministe sur le corpus local.

Structure du rapport :
  results/retrieval_eval_<horodatage>.json

Usage :
  python scripts/eval_retrieval.py
  python scripts/eval_retrieval.py --k 5 8 10
  python scripts/eval_retrieval.py --testset results/testset.json --k 8
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
from datetime import datetime

# ── Initialisation du chemin ───────────────────────────────────────────────────
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# Console Windows → forcer UTF-8
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

RESULTS_DIR = os.path.join(_ROOT, "results")
TESTSET_PATH = os.path.join(RESULTS_DIR, "testset.json")


# ── Métriques de retrieval ─────────────────────────────────────────────────────

def precision_at_k(retrieved_ids: list[str], relevant_ids: set[str], k: int) -> float:
    """Fraction des k premiers résultats pertinents."""
    if k == 0:
        return 0.0
    top_k = retrieved_ids[:k]
    hits = sum(1 for i in top_k if i in relevant_ids)
    return hits / k


def recall_at_k(retrieved_ids: list[str], relevant_ids: set[str], k: int) -> float:
    """Fraction des documents pertinents récupérés dans les k premiers."""
    if not relevant_ids:
        return 0.0
    top_k = retrieved_ids[:k]
    hits = sum(1 for i in top_k if i in relevant_ids)
    return hits / len(relevant_ids)


def f1_at_k(p: float, r: float) -> float:
    """Moyenne harmonique Precision / Recall."""
    if p + r == 0:
        return 0.0
    return 2 * p * r / (p + r)


def ndcg_at_k(retrieved_ids: list[str], relevant_ids: set[str], k: int) -> float:
    """
    Normalized Discounted Cumulative Gain @k.
    Gain binaire : 1 si pertinent, 0 sinon.
    Récompense les documents pertinents placés en tête de classement.
    """
    if not relevant_ids or k == 0:
        return 0.0
    top_k = retrieved_ids[:k]
    # DCG : somme pondérée par log2(position + 2) — position 0-indexée
    dcg = sum(
        (1.0 / math.log2(i + 2))
        for i, doc_id in enumerate(top_k)
        if doc_id in relevant_ids
    )
    # IDCG : classement idéal (tous les pertinents en tête)
    n_perfect = min(k, len(relevant_ids))
    idcg = sum(1.0 / math.log2(i + 2) for i in range(n_perfect))
    return dcg / idcg if idcg > 0 else 0.0


def mrr(retrieved_ids: list[str], relevant_ids: set[str]) -> float:
    """
    Mean Reciprocal Rank : 1/rang du 1er document pertinent trouvé.
    Retourne 0 si aucun document pertinent n'est dans la liste.
    """
    for i, doc_id in enumerate(retrieved_ids):
        if doc_id in relevant_ids:
            return 1.0 / (i + 1)
    return 0.0


# ── Chargement du testset ──────────────────────────────────────────────────────

def charger_testset(path: str) -> list[dict]:
    """Charge le testset JSON et retourne la liste des cas."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    cases = data.get("cases", data) if isinstance(data, dict) else data
    if not isinstance(cases, list):
        raise ValueError(f"Format testset inattendu : {type(cases)}")
    return cases


# ── Pipeline de retrieval ──────────────────────────────────────────────────────

def _retriever_chunks(query: str, k: int, use_reranker: bool) -> tuple[list[str], list[str]]:
    """
    Appelle le pipeline de retrieval (FAISS + reranker optionnel).

    Retourne (chunk_ids, article_ids) — deux listes ordonnées parallèles,
    permettant d'évaluer à la fois au niveau chunk ET au niveau article.

    Note : la déduplication par article_id (dans le pipeline reranker) réduit
    artificiellement le Recall@k chunk-level quand plusieurs chunks pertinents
    proviennent du même article. Les métriques article-level contournent ce biais.
    """
    from core.rag.retriever import rechercher
    from config import USE_RERANKER

    effective_use = use_reranker and USE_RERANKER

    if effective_use:
        from core.rag.reranker import reranker_chunks

        raw = rechercher(query=query, top_k=k * 3)

        for chunk in raw:
            if len(chunk.get("contenu", "")) < 200:
                chunk["score"] *= 0.7

        candidats = sorted(raw, key=lambda x: x["score"], reverse=True)[: k * 2]
        reranked = reranker_chunks(query, candidats, k * 2)

        vus_articles: set = set()
        chunks_uniques: list = []
        for chunk in reranked:
            art_id = chunk.get("article_id")
            if art_id not in vus_articles:
                chunks_uniques.append(chunk)
                vus_articles.add(art_id)
            if len(chunks_uniques) >= k:
                break

        chunk_ids   = [c["chunk_id"]   for c in chunks_uniques if c.get("chunk_id")]
        article_ids = [c["article_id"] for c in chunks_uniques if c.get("article_id")]
    else:
        raw = rechercher(query=query, top_k=k)
        chunk_ids   = [c["chunk_id"]   for c in raw if c.get("chunk_id")]
        article_ids = [c["article_id"] for c in raw if c.get("article_id")]

    return chunk_ids, article_ids


# ── Évaluation d'un cas ────────────────────────────────────────────────────────

def evaluer_cas(cas: dict, k_values: list[int], use_reranker: bool) -> dict:
    """
    Évalue un cas du testset pour toutes les valeurs de k.
    Calcule des métriques à deux niveaux de granularité :
      - Niveau chunk  : compare les chunk_ids récupérés aux relevant_chunk_ids du testset
      - Niveau article: compare les article_ids récupérés à l'article source du cas
        → contourne le biais de déduplication du pipeline reranker
    """
    question = cas["question"]
    relevant_chunk_ids  = set(cas.get("relevant_chunk_ids", []))
    # Ground truth article : l'article dont provenaient les chunks de référence
    relevant_article_id = cas.get("article_id")
    relevant_article_ids = {relevant_article_id} if relevant_article_id else set()

    k_max = max(k_values)
    retrieved_chunk_ids, retrieved_article_ids = _retriever_chunks(question, k_max, use_reranker)

    metriques_par_k: dict = {}
    for k in k_values:
        # Métriques chunk-level
        p  = precision_at_k(retrieved_chunk_ids, relevant_chunk_ids, k)
        r  = recall_at_k(retrieved_chunk_ids, relevant_chunk_ids, k)
        # Métriques article-level (hit binaire : est-ce que le bon article est parmi les k ?)
        p_art = precision_at_k(retrieved_article_ids[:k], relevant_article_ids, k)
        r_art = recall_at_k(retrieved_article_ids[:k], relevant_article_ids, k)
        hit_art = any(aid in relevant_article_ids for aid in retrieved_article_ids[:k])

        metriques_par_k[f"k{k}"] = {
            # Chunk-level
            "precision": round(p, 4),
            "recall":    round(r, 4),
            "f1":        round(f1_at_k(p, r), 4),
            "ndcg":      round(ndcg_at_k(retrieved_chunk_ids, relevant_chunk_ids, k), 4),
            # Article-level
            "article_hit":      int(hit_art),
            "article_precision": round(p_art, 4),
            "article_recall":    round(r_art, 4),
        }

    mrr_chunk   = mrr(retrieved_chunk_ids, relevant_chunk_ids)
    mrr_article = mrr(retrieved_article_ids, relevant_article_ids)
    hit_kmax    = any(i in relevant_chunk_ids for i in retrieved_chunk_ids[:k_max])
    hit_art_kmax = any(a in relevant_article_ids for a in retrieved_article_ids[:k_max])

    return {
        "id":              cas.get("id", ""),
        "question":        question[:80],
        "dimension":       cas.get("dimension", ""),
        "langue":          cas.get("langue", ""),
        "question_type":   cas.get("question_type", ""),
        "n_relevant":      len(relevant_chunk_ids),
        "n_retrieved":     len(retrieved_chunk_ids),
        "hit_at_kmax":     hit_kmax,
        "hit_art_at_kmax": hit_art_kmax,
        "mrr":             round(mrr_chunk, 4),
        "mrr_article":     round(mrr_article, 4),
        "metriques_par_k": metriques_par_k,
    }


# ── Agrégation ────────────────────────────────────────────────────────────────

def agreger(resultats: list[dict], k_values: list[int]) -> dict:
    """Calcule les moyennes de chaque métrique sur tous les cas."""
    n = len(resultats)
    if n == 0:
        return {}

    moyennes: dict = {}
    for k in k_values:
        key = f"k{k}"
        for metrique in ("precision", "recall", "f1", "ndcg",
                         "article_hit", "article_precision", "article_recall"):
            vals = [
                r["metriques_par_k"][key][metrique]
                for r in resultats
                if key in r.get("metriques_par_k", {})
                and metrique in r["metriques_par_k"][key]
            ]
            label = f"{metrique}@{k}"
            moyennes[label] = round(sum(vals) / len(vals), 4) if vals else 0.0

    mrr_chunk_vals   = [r["mrr"]         for r in resultats]
    mrr_article_vals = [r["mrr_article"] for r in resultats]
    moyennes["mrr"]         = round(sum(mrr_chunk_vals)   / n, 4)
    moyennes["mrr_article"] = round(sum(mrr_article_vals) / n, 4)

    hit_vals     = [1.0 if r["hit_at_kmax"]     else 0.0 for r in resultats]
    hit_art_vals = [1.0 if r["hit_art_at_kmax"] else 0.0 for r in resultats]
    kmax = max(k_values)
    moyennes[f"hit_rate@{kmax}"]         = round(sum(hit_vals)     / n, 4)
    moyennes[f"article_hit_rate@{kmax}"] = round(sum(hit_art_vals) / n, 4)

    return moyennes


def agreger_par_dimension(resultats: list[dict], k_values: list[int]) -> dict:
    """Même calcul, ventilé par dimension IF."""
    from collections import defaultdict
    par_dim: dict = defaultdict(list)
    for r in resultats:
        par_dim[r.get("dimension") or "Inconnu"].append(r)

    return {
        dim: agreger(cases, k_values)
        for dim, cases in par_dim.items()
    }


# ── Affichage console ──────────────────────────────────────────────────────────

def afficher_rapport(moyennes: dict, k_values: list[int], n: int, use_reranker: bool):
    reranker_label = "FAISS + cross-encoder" if use_reranker else "FAISS seul"
    kmax = max(k_values)
    print()
    print("=" * 65)
    print(f"  ÉVALUATION RETRIEVAL — {reranker_label}")
    print(f"  {n} questions du testset annoté")
    print("=" * 65)
    for k in k_values:
        print(f"\n  ── Niveau CHUNK @k={k}")
        print(f"    Precision@{k}         : {moyennes.get(f'precision@{k}', 0):.4f}")
        print(f"    Recall@{k}            : {moyennes.get(f'recall@{k}', 0):.4f}")
        print(f"    F1@{k}               : {moyennes.get(f'f1@{k}', 0):.4f}")
        print(f"    NDCG@{k}             : {moyennes.get(f'ndcg@{k}', 0):.4f}")
        print(f"  ── Niveau ARTICLE @k={k}")
        print(f"    Article Hit Rate@{k}  : {moyennes.get(f'article_hit@{k}', 0):.4f}")
        print(f"    Article Precision@{k} : {moyennes.get(f'article_precision@{k}', 0):.4f}")
        print(f"    Article Recall@{k}    : {moyennes.get(f'article_recall@{k}', 0):.4f}")
    print(f"\n  MRR (chunk)        : {moyennes.get('mrr', 0):.4f}")
    print(f"  MRR (article)      : {moyennes.get('mrr_article', 0):.4f}")
    print(f"  Hit Rate@{kmax} (chunk)  : {moyennes.get(f'hit_rate@{kmax}', 0):.4f}")
    print(f"  Hit Rate@{kmax} (article): {moyennes.get(f'article_hit_rate@{kmax}', 0):.4f}")
    print("=" * 65)
    print()


# ── Point d'entrée ─────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Évaluation du retrieval (Precision, Recall, NDCG, MRR)."
    )
    parser.add_argument(
        "--testset", default=TESTSET_PATH,
        help="Chemin vers le fichier testset.json (défaut : results/testset.json)."
    )
    parser.add_argument(
        "--k", nargs="+", type=int, default=[5, 8, 10],
        help="Valeur(s) de k à évaluer (ex: --k 5 8 10)."
    )
    parser.add_argument(
        "--no-reranker", action="store_true",
        help="Désactiver le reranker cross-encoder (évalue FAISS seul)."
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Afficher les résultats cas par cas."
    )
    args = parser.parse_args()

    # ── Chargement du testset
    if not os.path.exists(args.testset):
        print(f"[ERREUR] Testset introuvable : {args.testset}")
        print("  -> Lancez d'abord : python scripts/generate_testset.py --n 30")
        return 1

    cases = charger_testset(args.testset)
    if not cases:
        print("[ERREUR] Testset vide.")
        return 1

    k_values = sorted(set(args.k))
    use_reranker = not args.no_reranker

    reranker_label = "FAISS + cross-encoder" if use_reranker else "FAISS seul"
    log.info("Testset : %d cas | k=%s | pipeline=%s", len(cases), k_values, reranker_label)
    log.info("Chargement du modele d'embedding...")

    resultats = []
    for i, cas in enumerate(cases, 1):
        log.info("  [%d/%d] %s", i, len(cases), cas.get("question", "")[:60])
        try:
            res = evaluer_cas(cas, k_values, use_reranker)
            resultats.append(res)
            if args.verbose:
                k_str = " | ".join(
                    "P@{}={:.2f} R@{}={:.2f} NDCG@{}={:.2f}".format(
                        k, res["metriques_par_k"][f"k{k}"]["precision"],
                        k, res["metriques_par_k"][f"k{k}"]["recall"],
                        k, res["metriques_par_k"][f"k{k}"]["ndcg"])
                    for k in k_values
                )
                print("    {} | MRR={:.2f}".format(k_str, res["mrr"]))
        except Exception as e:
            log.warning("  Cas %s ignore (%s: %s)", cas.get("id", "?"), type(e).__name__, e)

    if not resultats:
        print("[ERREUR] Aucun resultat produit.")
        return 1

    moyennes = agreger(resultats, k_values)
    par_dimension = agreger_par_dimension(resultats, k_values)
    afficher_rapport(moyennes, k_values, len(resultats), use_reranker)

    os.makedirs(RESULTS_DIR, exist_ok=True)
    horodatage = datetime.now().strftime("%Y%m%d_%H%M%S")
    sortie = os.path.join(RESULTS_DIR, "retrieval_eval_{}.json".format(horodatage))
    payload = {
        "type":          "retrieval",
        "date":          datetime.now().isoformat(),
        "pipeline":      reranker_label,
        "use_reranker":  use_reranker,
        "k_values":      k_values,
        "n_cas":         len(resultats),
        "moyennes":      moyennes,
        "par_dimension": par_dimension,
        "cas":           resultats,
    }
    with open(sortie, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print("[OK] Resultats sauvegardes : {}".format(os.path.relpath(sortie, _ROOT)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
