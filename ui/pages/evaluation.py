"""
ui/pages/evaluation.py — Page admin « Évaluation ».

Affiche uniquement des éléments RÉELS :
  1. statistiques sur les interactions chatbot réellement enregistrées ;
  2. résultats de l'évaluation AGENTIQUE (results/agentic_eval_*.json) produits
     par scripts/eval_agentique.py — exécution réelle de l'agent + juge.

Lecture seule : aucun calcul en direct (les métriques sont produites hors-ligne).
"""
import streamlit as st
import sys, os, json, glob
sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
from core.database import get_stats_interactions

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_RESULTS_DIR = os.path.join(_ROOT, "results")


def _dernier_resultat(prefixe: str) -> dict | None:
    """Charge le fichier results/<prefixe>_*.json le plus récent, ou None."""
    fichiers = sorted(glob.glob(os.path.join(_RESULTS_DIR, f"{prefixe}_*.json")))
    if not fichiers:
        return None
    try:
        with open(fichiers[-1], "r", encoding="utf-8") as f:
            data = json.load(f)
        data["_fichier"] = os.path.basename(fichiers[-1])
        return data
    except Exception as e:
        st.error(f"Lecture impossible de {os.path.basename(fichiers[-1])} : {e}")
        return None


def _lancer_eval_agentique(n_sample: int):
    """Exécute scripts/eval_agentique.py en sous-process (isolé). Retourne (ok, log)."""
    import subprocess
    script = os.path.join(_ROOT, "scripts", "eval_agentique.py")
    try:
        res = subprocess.run(
            [sys.executable, script, "--sample", str(n_sample)],
            cwd=_ROOT, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=1800,
        )
        return res.returncode == 0, (res.stdout or "") + (res.stderr or "")
    except subprocess.TimeoutExpired:
        return False, "Délai dépassé (1800 s)."
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


# ──────────────────────────────────────────────────────────────────────────────
# Onglet 1 — Interactions chatbot (données réelles)
# ──────────────────────────────────────────────────────────────────────────────

def _onglet_interactions():
    stats = get_stats_interactions()

    if stats["total"] == 0:
        st.info("Aucune interaction chatbot enregistrée pour l'instant.")
        return

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Interactions", stats["total"])
    c2.metric("Avec feedback", stats["avec_feedback"])
    c3.metric("👍 Positifs", stats["feedback_positif"])
    c4.metric("👎 Négatifs", stats["feedback_negatif"])

    import plotly.express as px

    col_g, col_d = st.columns(2)
    with col_g:
        st.markdown("**Dimensions détectées**")
        dims = stats["par_dimension"]
        if dims:
            fig = px.bar(
                x=[d["nb"] for d in dims],
                y=[d["dimension"] for d in dims],
                orientation="h",
                labels={"x": "Interactions", "y": ""},
                color_discrete_sequence=["#002B5C"],
            )
            fig.update_layout(height=320, margin=dict(l=0, r=0, t=10, b=0))
            st.plotly_chart(fig, use_container_width=True)

    with col_d:
        st.markdown("**Distribution des scores de chunks récupérés**")
        scores = stats["scores_chunks"]
        if scores:
            fig = px.histogram(
                x=scores, nbins=20,
                labels={"x": "Score de pertinence", "y": "Nb chunks"},
                color_discrete_sequence=["#C8A951"],
            )
            fig.update_layout(height=320, margin=dict(l=0, r=0, t=10, b=0))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.caption("Aucun score de chunk disponible.")

    par_jour = stats["par_jour"]
    if par_jour:
        st.markdown("**Volume d'interactions par jour**")
        par_jour = sorted(par_jour, key=lambda r: r["jour"])
        fig = px.line(
            x=[r["jour"] for r in par_jour],
            y=[r["nb"] for r in par_jour],
            markers=True,
            labels={"x": "", "y": "Interactions"},
            color_discrete_sequence=["#27AE60"],
        )
        fig.update_layout(height=260, margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig, use_container_width=True)


# ──────────────────────────────────────────────────────────────────────────────
# Onglet 2 — Évaluation agentique (exécution réelle de l'agent)
# ──────────────────────────────────────────────────────────────────────────────

def _fmt_pct(v):
    return f"{v * 100:.0f}%" if isinstance(v, (int, float)) else "—"


def _fmt_num(v, n=3):
    return f"{v:.{n}f}" if isinstance(v, (int, float)) else "—"


def _onglet_agentique():
    # ── Lancement de l'évaluation au clic (sous-process, sans terminal) ──
    nb_inter = get_stats_interactions()["total"]
    col_n, col_b = st.columns([1, 2])
    with col_n:
        n_sample = st.number_input(
            "Questions à évaluer", min_value=1, max_value=50,
            value=min(10, max(1, nb_inter)), step=1, key="eval_n_sample",
        )
    with col_b:
        st.caption(
            f"{nb_inter} question(s) réelle(s) disponible(s). "
            "L'évaluation exécute l'agent + le juge (~30 s/question) — "
            "patientez quelques minutes."
        )
        if st.button("▶ Lancer l'évaluation maintenant",
                     disabled=(nb_inter == 0), use_container_width=True):
            with st.spinner(
                f"Évaluation de {int(n_sample)} question(s) en cours… "
                "(exécution réelle de l'agent + juge)"
            ):
                ok, journal = _lancer_eval_agentique(int(n_sample))
            if ok:
                st.success("Évaluation terminée.")
                st.rerun()
            else:
                st.error("Échec de l'évaluation.")
                st.code((journal or "")[-1500:])
        if nb_inter == 0:
            st.caption("Utilisez d'abord le **Chatbot** pour générer des interactions.")

    st.markdown("---")

    data = _dernier_resultat("agentic_eval")
    if not data:
        st.info("Aucun résultat pour l'instant — lancez une évaluation ci-dessus.")
        return

    st.caption(
        f"Fichier : {data['_fichier']} · source : {data.get('source', '?')} · "
        f"{data.get('n_questions', '?')} questions · juge : "
        f"{data.get('judge_model', '?')} · {(data.get('date') or '')[:19]}"
    )

    rap = data.get("rapport", {}) or {}
    avg = rap.get("averages", {}) or {}

    st.markdown("**Comportement agentique** (la boucle d'outils du LLM)")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Recherche appelée",    _fmt_pct(avg.get("search_corpus_appele")))
    c2.metric("Reformulation",        _fmt_pct(avg.get("reformulation")))
    c3.metric("Recherches / question", _fmt_num(avg.get("nb_recherches"), 2))
    c4.metric("Sources non vides",    _fmt_pct(avg.get("sources_non_vides")))

    st.markdown("**Qualité de la réponse** (juge LLM, sans référence — automatique)")
    d1, d2, d3, d4 = st.columns(4)
    d1.metric("Faithfulness",      _fmt_num(avg.get("faithfulness")))
    d2.metric("Answer relevancy",  _fmt_num(avg.get("answer_relevancy")))
    d3.metric("Context relevance", _fmt_num(avg.get("context_relevance")))
    d4.metric("Qualité globale",   _fmt_num(avg.get("qualite_globale")))

    cases = rap.get("cases", []) or []
    if cases:
        with st.expander(f"Détail par question ({len(cases)})"):
            lignes = []
            for c in cases:
                row = {
                    "Question":  (c.get("name") or "")[:70],
                    "Dimension": c.get("dimension"),
                    "Durée (s)": c.get("duree_s"),
                }
                for k, v in (c.get("scores") or {}).items():
                    row[k] = round(v, 3) if isinstance(v, (int, float)) else v
                lignes.append(row)
            st.dataframe(lignes, use_container_width=True, hide_index=True)


# ──────────────────────────────────────────────────────────────────────────────
# Point d'entrée
# ──────────────────────────────────────────────────────────────────────────────

def render_evaluation(user):
    st.title("Évaluation")
    st.caption(
        "Suivi réel du système RAG agentique : interactions réelles et "
        "évaluation par exécution réelle de l'agent (pydantic-evals)."
    )

    onglet_inter, onglet_agent = st.tabs(
        ["Interactions chatbot", "Évaluation agentique"]
    )
    with onglet_inter:
        _onglet_interactions()
    with onglet_agent:
        _onglet_agentique()
