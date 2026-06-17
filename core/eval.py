"""
core/eval.py — Métriques d'évaluation du retrieval (fonctions pures).

Aucune dépendance réseau, base de données ou FAISS : ce module ne manipule
que des listes d'identifiants. Il est donc testable unitairement sans appel
externe (voir tests/test_eval.py).

Convention : `retrieved_ids` est une liste ORDONNÉE d'article_id renvoyés par
le retrieval (du plus pertinent au moins pertinent), idéalement dédupliquée
au niveau article. `relevant_ids` est l'ensemble des article_id attendus.
"""
from __future__ import annotations

from typing import Iterable


def dedupe_ordre(ids: Iterable) -> list:
    """Déduplique une liste en conservant l'ordre de première apparition."""
    vus: set = set()
    out: list = []
    for x in ids:
        if x is None:
            continue
        if x not in vus:
            vus.add(x)
            out.append(x)
    return out


def recall_at_k(retrieved_ids: list, relevant_ids: Iterable, k: int) -> float:
    """
    Recall@k = (nb d'attendus présents dans le top-k) / (nb total d'attendus).
    Retourne 0.0 si aucun attendu n'est défini.
    """
    relevant = set(relevant_ids)
    if not relevant:
        return 0.0
    top = retrieved_ids[:k]
    trouves = sum(1 for r in relevant if r in top)
    return trouves / len(relevant)


def precision_at_k(retrieved_ids: list, relevant_ids: Iterable, k: int) -> float:
    """
    Precision@k = (nb de pertinents dans le top-k) / (taille du top-k réel).
    Le dénominateur est min(k, nb réellement récupérés) afin de ne pas pénaliser
    les cas où moins de k résultats sont renvoyés. Retourne 0.0 si rien n'est
    récupéré.
    """
    if k <= 0:
        return 0.0
    relevant = set(relevant_ids)
    top = retrieved_ids[:k]
    if not top:
        return 0.0
    hits = sum(1 for r in top if r in relevant)
    return hits / len(top)


def reciprocal_rank(retrieved_ids: list, relevant_ids: Iterable) -> float:
    """
    Rang réciproque : 1 / (rang du premier résultat pertinent), 0.0 si aucun.
    Les rangs commencent à 1.
    """
    relevant = set(relevant_ids)
    for i, rid in enumerate(retrieved_ids, start=1):
        if rid in relevant:
            return 1.0 / i
    return 0.0


def ndcg_at_k(retrieved_ids: list, relevant_ids: Iterable, k: int) -> float:
    """
    nDCG@k avec pertinence binaire (gain 1 si pertinent, 0 sinon).
    DCG = Σ 1/log2(rang+1) sur les pertinents du top-k ; normalisé par le DCG
    idéal (tous les pertinents en tête). Retourne 0.0 si aucun pertinent.
    """
    import math
    relevant = set(relevant_ids)
    top = retrieved_ids[:k]
    if not relevant or not top:
        return 0.0
    dcg = sum(
        1.0 / math.log2(rang + 2)
        for rang, rid in enumerate(top)
        if rid in relevant
    )
    ideal = sum(
        1.0 / math.log2(rang + 2)
        for rang in range(min(len(relevant), k))
    )
    return dcg / ideal if ideal > 0 else 0.0


def evaluer_question(retrieved_ids: list,
                     relevant_ids: Iterable,
                     k: int) -> dict:
    """Calcule les trois métriques pour une question (après déduplication)."""
    ordered = dedupe_ordre(retrieved_ids)
    return {
        "recall@k":    recall_at_k(ordered, relevant_ids, k),
        "precision@k": precision_at_k(ordered, relevant_ids, k),
        "rr":          reciprocal_rank(ordered, relevant_ids),
    }


def moyenne_metriques(resultats: list) -> dict:
    """
    Moyenne les métriques sur une liste de dicts produits par evaluer_question.
    MRR = moyenne des rangs réciproques. Retourne des zéros si la liste est vide.
    """
    n = len(resultats)
    if n == 0:
        return {"recall@k": 0.0, "precision@k": 0.0, "mrr": 0.0, "n": 0}
    return {
        "recall@k":    sum(r["recall@k"] for r in resultats) / n,
        "precision@k": sum(r["precision@k"] for r in resultats) / n,
        "mrr":         sum(r["rr"] for r in resultats) / n,
        "n":           n,
    }
