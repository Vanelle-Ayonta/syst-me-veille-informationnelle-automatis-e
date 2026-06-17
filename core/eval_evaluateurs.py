"""
core/eval_evaluateurs.py — Évaluateurs pydantic-evals pour le RAG agentique.

Évaluateur pur (sans appel réseau) opérant sur la sortie d'un run de l'agent :
  - TrajectoireAgentique : l'agent a-t-il appelé l'outil de recherche, reformulé,
    récupéré des sources ? (qualité de la BOUCLE agentique)

La qualité de la génération est évaluée séparément, sans référence, par le juge
LLM structuré (voir MetriquesSansReference dans scripts/eval_agentique.py).
"""
from __future__ import annotations

from dataclasses import dataclass

from pydantic_evals.evaluators import Evaluator, EvaluatorContext


@dataclass
class TrajectoireAgentique(Evaluator):
    """Métriques propres au comportement agentique (sans LLM, instantanées)."""

    def evaluate(self, ctx: EvaluatorContext) -> dict:
        out = ctx.output
        outils = list(getattr(out, "outils", []) or [])
        nb_rech = int(getattr(out, "nb_recherches", 0) or 0)
        article_ids = getattr(out, "article_ids", []) or []
        return {
            "search_corpus_appele": 1.0 if "search_corpus" in outils else 0.0,
            "reformulation":        1.0 if nb_rech > 1 else 0.0,
            "nb_recherches":        float(nb_rech),
            "sources_non_vides":    1.0 if article_ids else 0.0,
        }
