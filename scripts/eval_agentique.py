"""
scripts/eval_agentique.py — Harnais d'évaluation du RAG AGENTIQUE (pydantic-evals).

Deux modes d'évaluation (Niveau 3 / 3 niveaux) :

Mode A — questions réelles (défaut) :
  Évalue sur les VRAIES questions posées au chatbot (table interactions_chatbot).
  Pas de vérité terrain → métriques sans référence uniquement.

Mode B — testset annoté (--testset) :
  Évalue sur le jeu de test généré par generate_testset.py, qui contient des
  réponses de référence. Active en plus :
    - answer_similarity : proximité sémantique réponse / référence (juge LLM)
  Usage : python scripts/eval_agentique.py --testset

Métriques communes (juge LLM structuré) :
  - faithfulness      : réponse ancrée dans le contexte (sans hallucination)
  - answer_relevancy  : réponse pertinente par rapport à la question
  - context_relevance : contexte récupéré pertinent pour la question
  - qualite_globale   : exactitude, clarté, structure, sources citées

Métriques agentiques (instantanées, sans LLM) :
  - search_corpus_appele : l'agent a-t-il appelé l'outil de recherche ?
  - reformulation        : plus d'une recherche (reformulation détectée) ?
  - nb_recherches        : nombre total d'appels à search_corpus
  - sources_non_vides    : au moins une source renvoyée ?

100 % local : seul appel externe = le juge Anthropic (déjà utilisé par le système).

Usage :
  python scripts/eval_agentique.py --sample 10
  python scripts/eval_agentique.py --testset
  python scripts/eval_agentique.py --testset --sample 15 --k 8
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime

from pydantic import BaseModel, Field

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# Console Windows en cp1252 → forcer UTF-8 pour l'affichage rich (✔, accents…)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from pydantic_evals.evaluators import Evaluator

from config import ANTHROPIC_MODEL_FAST
from core.eval import dedupe_ordre

RESULTS_DIR = os.path.join(_ROOT, "results")


# ── Types d'E/S manipulés par pydantic-evals ───────────────────────────────────

@dataclass
class SortieEval:
    """Sortie d'un run de l'agent, consommée par les évaluateurs."""
    reponse: str
    article_ids: list = field(default_factory=list)
    outils: list = field(default_factory=list)
    nb_recherches: int = 0
    contexte: str = ""   # contexte récupéré (pour juger l'ancrage / faithfulness)


class ScoresJuge(BaseModel):
    """Scores sans référence produits par le juge LLM (0 à 1)."""
    faithfulness: float = Field(ge=0, le=1,
        description="Réponse étayée par le contexte (0=hallucine, 1=ancrée)")
    answer_relevancy: float = Field(ge=0, le=1,
        description="La réponse répond à la question")
    context_relevance: float = Field(ge=0, le=1,
        description="Le contexte récupéré est pertinent pour la question")
    qualite_globale: float = Field(ge=0, le=1,
        description="Exactitude, clarté, structure, sources citées")


class ScoresJugeAvecReference(BaseModel):
    """Scores avec référence produits par le juge LLM (0 à 1)."""
    faithfulness: float = Field(ge=0, le=1,
        description="Réponse étayée par le contexte (0=hallucine, 1=ancrée)")
    answer_relevancy: float = Field(ge=0, le=1,
        description="La réponse répond à la question")
    context_relevance: float = Field(ge=0, le=1,
        description="Le contexte récupéré est pertinent pour la question")
    qualite_globale: float = Field(ge=0, le=1,
        description="Exactitude, clarté, structure, sources citées")
    answer_similarity: float = Field(ge=0, le=1,
        description="Similarité sémantique entre la réponse et la réponse de référence")


# ── Chargement des questions ───────────────────────────────────────────────────

def _cases_depuis_testset(limite=None):
    """
    Charge les cas depuis results/testset.json (questions annotées avec référence).
    Retourne des pydantic-evals Case avec expected_output = réponse de référence.
    """
    import os as _os
    from pydantic_evals import Case

    testset_path = _os.path.join(RESULTS_DIR, "testset.json")
    if not _os.path.exists(testset_path):
        raise FileNotFoundError(
            f"Testset introuvable : {testset_path}\n"
            "  → Lancez d'abord : python scripts/generate_testset.py --n 30"
        )
    with open(testset_path, "r", encoding="utf-8") as f:
        import json as _json
        data = _json.load(f)
    raw_cases = data.get("cases", []) if isinstance(data, dict) else data

    cases = []
    for c in raw_cases:
        question = (c.get("question") or "").strip()
        if not question:
            continue
        cases.append(Case(
            name=c.get("id", question[:60]),
            inputs=question,
            expected_output=c.get("reference_answer", ""),
            metadata={
                "dimension":     c.get("dimension"),
                "langue":        c.get("langue"),
                "question_type": c.get("question_type"),
                "article_id":    c.get("article_id"),
                "source":        "testset",
            },
        ))
    return cases[:limite] if limite else cases


def _cases_depuis_interactions(limite=None):
    """
    Vraies questions de connaissance posées au chatbot (sans vérité terrain).
    Exclut salutations et fragments trop courts (non pertinents pour une éval RAG).
    """
    from pydantic_evals import Case
    from core.database import get_db
    from agents.svia_agent import _est_salutation

    with get_db() as conn:
        rows = conn.execute("""
            SELECT requete_utilisateur, dimension_detectee,
                   MAX(horodatage) AS h
            FROM interactions_chatbot
            WHERE requete_utilisateur IS NOT NULL
            GROUP BY requete_utilisateur
            ORDER BY h DESC
        """).fetchall()
    cases = []
    for r in rows:
        q = (r["requete_utilisateur"] or "").strip()
        # Ne garder que de vraies questions : exclure salutations et fragments.
        if len(q) < 12 or _est_salutation(q):
            continue
        cases.append(Case(
            name=q[:60],
            inputs=q,
            metadata={"dimension": r["dimension_detectee"], "source": "interactions"},
            expected_output=None,
        ))
    return cases[:limite] if limite else cases


# ── Tâche : exécute le vrai agent agentique ────────────────────────────────────

def _faire_tache(top_k: int):
    from core.schemas import SVIADeps
    from agents.svia_agent import svia_chat_agent
    from pydantic_ai.messages import ModelResponse, ToolCallPart

    async def tache(question: str) -> SortieEval:
        deps = SVIADeps(historique=[], top_k=top_k)
        result = await svia_chat_agent.run(question, deps=deps)
        outils = []
        for m in result.all_messages():
            if isinstance(m, ModelResponse):
                for p in m.parts:
                    if isinstance(p, ToolCallPart) and p.tool_name != "final_result":
                        outils.append(p.tool_name)
        article_ids = dedupe_ordre(
            [c.get("article_id") for c in deps.chunks_trouves])
        return SortieEval(
            reponse=result.output,
            article_ids=article_ids,
            outils=outils,
            nb_recherches=sum(1 for o in outils if o == "search_corpus"),
            contexte=(deps.contexte_formate or "")[:8000],
        )

    return tache


# ── Juge LLM structuré — métriques SANS référence (aucune annotation humaine) ──

_SYSTEME_JUGE = """\
Tu es un évaluateur rigoureux de réponses d'un assistant RAG (inclusion
financière, zone CEMAC). On te donne une QUESTION, le CONTEXTE récupéré et la
RÉPONSE. Note chaque critère entre 0 et 1 (sans référence externe) :
- faithfulness : la réponse est-elle entièrement étayée par le contexte ?
  (1 = aucune affirmation inventée ; 0 = hallucinations majeures)
- answer_relevancy : la réponse répond-elle directement à la question ?
- context_relevance : le contexte récupéré est-il pertinent pour la question ?
- qualite_globale : exactitude, clarté, structure, sources citées.
Sois strict : pénalise toute affirmation absente du contexte.
"""

_SYSTEME_JUGE_AVEC_REF = """\
Tu es un évaluateur rigoureux de réponses d'un assistant RAG (inclusion
financière, zone CEMAC). On te donne une QUESTION, le CONTEXTE récupéré,
la RÉPONSE de l'assistant et une RÉPONSE DE RÉFÉRENCE (ground truth).
Note chaque critère entre 0 et 1 :
- faithfulness : la réponse est-elle entièrement étayée par le contexte ?
  (1 = aucune affirmation inventée ; 0 = hallucinations majeures)
- answer_relevancy : la réponse répond-elle directement à la question ?
- context_relevance : le contexte récupéré est-il pertinent pour la question ?
- qualite_globale : exactitude, clarté, structure, sources citées.
- answer_similarity : dans quelle mesure la réponse de l'assistant couvre-t-elle
  les mêmes informations factuelles que la référence ?
  (1 = informations identiques ; 0 = complètement différentes)
Sois strict : pénalise toute affirmation absente du contexte.
"""

_JUGE = None
_JUGE_REF = None


def _get_juge():
    """Agent juge structuré sans référence (modèle rapide), construit une seule fois."""
    global _JUGE
    if _JUGE is None:
        from pydantic_ai import Agent
        from agents.svia_agent import _build_model
        _JUGE = Agent(
            model=_build_model(fast=True),
            output_type=ScoresJuge,
            system_prompt=_SYSTEME_JUGE,
        )
    return _JUGE


def _get_juge_ref():
    """Agent juge structuré AVEC référence (modèle rapide), construit une seule fois."""
    global _JUGE_REF
    if _JUGE_REF is None:
        from pydantic_ai import Agent
        from agents.svia_agent import _build_model
        _JUGE_REF = Agent(
            model=_build_model(fast=True),
            output_type=ScoresJugeAvecReference,
            system_prompt=_SYSTEME_JUGE_AVEC_REF,
        )
    return _JUGE_REF


@dataclass
class MetriquesSansReference(Evaluator):
    """
    Évaluateur LLM SANS référence (aucune annotation humaine) : faithfulness,
    answer_relevancy, context_relevance, qualité globale. Un seul appel juge.
    """

    async def evaluate(self, ctx) -> dict:
        out = ctx.output
        # Pas de contexte récupéré (aucune recherche) → l'ancrage / la pertinence
        # du contexte ne sont pas pertinents : on n'invente pas de score à 0.
        if not (out.contexte or "").strip():
            return {}
        prompt = (
            f"QUESTION :\n{ctx.inputs}\n\n"
            f"CONTEXTE récupéré :\n{out.contexte}\n\n"
            f"RÉPONSE de l'assistant :\n{out.reponse or '(vide)'}"
        )
        try:
            res = await _get_juge().run(prompt)
            s = res.output
            return {
                "faithfulness":      s.faithfulness,
                "answer_relevancy":  s.answer_relevancy,
                "context_relevance": s.context_relevance,
                "qualite_globale":   s.qualite_globale,
            }
        except Exception as e:
            print(f"    [WARN] juge sans référence échoué : "
                  f"{type(e).__name__}: {str(e)[:80]}")
            return {}


@dataclass
class MetriquesAvecReference(Evaluator):
    """
    Évaluateur LLM AVEC référence (testset annoté) : ajoute answer_similarity
    à toutes les métriques sans référence. Un seul appel juge.
    """

    async def evaluate(self, ctx) -> dict:
        out = ctx.output
        reference = ctx.expected_output or ""

        if not (out.contexte or "").strip():
            return {}

        prompt = (
            f"QUESTION :\n{ctx.inputs}\n\n"
            f"CONTEXTE récupéré :\n{out.contexte}\n\n"
            f"RÉPONSE de l'assistant :\n{out.reponse or '(vide)'}\n\n"
            f"RÉPONSE DE RÉFÉRENCE (ground truth) :\n{reference or '(non disponible)'}"
        )
        try:
            res = await _get_juge_ref().run(prompt)
            s = res.output
            return {
                "faithfulness":      s.faithfulness,
                "answer_relevancy":  s.answer_relevancy,
                "context_relevance": s.context_relevance,
                "qualite_globale":   s.qualite_globale,
                "answer_similarity": s.answer_similarity,
            }
        except Exception as e:
            print(f"    [WARN] juge avec référence échoué : "
                  f"{type(e).__name__}: {str(e)[:80]}")
            return {}


def _val(res):
    """Valeur scalaire d'un score/résultat pydantic-evals."""
    return getattr(res, "value", res)


def _scores_dict(obj) -> dict:
    return {nom: _val(res) for nom, res in (getattr(obj, "scores", {}) or {}).items()}


def _serialiser_rapport(report) -> dict:
    """Extrait un dict JSON-sérialisable (par cas + moyennes) d'un EvaluationReport."""
    cases = []
    for c in getattr(report, "cases", []) or []:
        meta = getattr(c, "metadata", None) or {}
        cases.append({
            "name":      getattr(c, "name", ""),
            "dimension": meta.get("dimension") if isinstance(meta, dict) else None,
            "source":    meta.get("source") if isinstance(meta, dict) else None,
            "scores":    _scores_dict(c),
            "duree_s":   round(getattr(c, "task_duration", 0) or 0, 1),
        })
    averages = {}
    try:
        averages = _scores_dict(report.averages())
    except Exception:
        pass
    return {"averages": averages, "cases": cases}


def main() -> int:
    parser = argparse.ArgumentParser(description="Éval RAG agentique (pydantic-evals).")
    parser.add_argument("--sample", type=int, default=None,
                        help="Limiter au N premières questions.")
    parser.add_argument("--k", type=int, default=8)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument(
        "--testset", action="store_true",
        help=(
            "Utiliser le testset annoté (results/testset.json) au lieu des "
            "vraies interactions chatbot. Active l'évaluateur avec référence "
            "(answer_similarity)."
        ),
    )
    args = parser.parse_args()

    from config import ANTHROPIC_API_KEY
    if not ANTHROPIC_API_KEY:
        print("[ERREUR] ANTHROPIC_API_KEY absente (agent + juge).")
        return 1

    from pydantic_evals import Dataset
    from pydantic_evals.evaluators import MaxDuration
    from core.eval_evaluateurs import TrajectoireAgentique

    # ── Chargement des cas
    if args.testset:
        try:
            cases = _cases_depuis_testset(args.sample)
        except FileNotFoundError as e:
            print(f"[ERREUR] {e}")
            return 1
        source_label = "testset"
        evaluateur_generation = MetriquesAvecReference()   # + answer_similarity
    else:
        cases = _cases_depuis_interactions(args.sample)
        source_label = "interactions"
        evaluateur_generation = MetriquesSansReference()   # sans référence

    if not cases:
        if args.testset:
            print("[ERREUR] Testset vide. Vérifiez results/testset.json.")
        else:
            print("[ERREUR] Aucune vraie question dans interactions_chatbot. "
                  "Utilisez d'abord le chatbot pour générer des interactions.")
        return 1

    print(f"[INFO] {len(cases)} question(s) | source={source_label} | "
          f"juge={ANTHROPIC_MODEL_FAST}")

    evaluateurs = [
        TrajectoireAgentique(),
        MaxDuration(seconds=90),
        evaluateur_generation,
    ]

    dataset = Dataset(cases=cases, evaluators=evaluateurs)
    tache = _faire_tache(args.k)

    print("[INFO] Évaluation en cours (exécution réelle de l'agent + juge)...")
    report = dataset.evaluate_sync(tache, max_concurrency=args.concurrency)

    # Sauvegarde de l'artefact JSON D'ABORD (indépendant de l'affichage console)
    os.makedirs(RESULTS_DIR, exist_ok=True)
    horodatage = datetime.now().strftime("%Y%m%d_%H%M%S")
    sortie = os.path.join(RESULTS_DIR, f"agentic_eval_{horodatage}.json")
    payload = {
        "type":         "agentique",
        "date":         datetime.now().isoformat(),
        "source":       source_label,
        "avec_reference": args.testset,
        "judge_model":  ANTHROPIC_MODEL_FAST,
        "k":            args.k,
        "n_questions":  len(cases),
        "rapport":      _serialiser_rapport(report),
    }
    with open(sortie, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
    print(f"[OK] Résultats écrits dans : {os.path.relpath(sortie, _ROOT)}")

    # Rapport console (table pydantic-evals) — non bloquant
    try:
        report.print(include_input=False, include_output=False)
    except Exception as e:
        print(f"[INFO] Affichage table ignoré ({type(e).__name__}). "
              f"Voir le JSON pour le détail.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
