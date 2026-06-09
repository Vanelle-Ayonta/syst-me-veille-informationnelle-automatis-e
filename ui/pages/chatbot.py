"""
ui/pages/chatbot.py — Interface du chatbot DIIF
Chatbot conversationnel avec historique de session,
sources citées et suggestions actionnables.
"""
import streamlit as st
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
from config import DIMENSIONS_IF, CIBLES_IF, ZONES_CEMAC


def render_chatbot(user):
    st.title("Chatbot DIIF")
    st.caption(
        "Posez vos questions sur l'inclusion et l'innovation "
        "financières — je réponds à partir des documents collectés."
    )

    # Initialisation de l'historique de session
    if "chat_historique" not in st.session_state:
        st.session_state["chat_historique"] = []
    if "chat_sources" not in st.session_state:
        st.session_state["chat_sources"] = []
    if "chat_suggestions" not in st.session_state:
        st.session_state["chat_suggestions"] = []

    # Vérifier que l'index RAG est disponible
    try:
        from core.rag.indexer import get_stats_index
        stats = get_stats_index()
        if not stats.get("index_existe") or stats.get("total_vecteurs", 0) == 0:
            st.warning(
                "L'index RAG est vide. "
                "Lancez d'abord : `python core/rag/run_pipeline.py`"
            )
            return
    except Exception:
        st.error("Erreur de connexion au pipeline RAG.")
        return

    # CSS sidebar — injecté avant tout widget pour garantir la priorité
    st.markdown("""
<style>
/* Labels des filtres */
[data-testid="stSidebar"] label {
    color: #C8A951 !important;
    font-weight: 500 !important;
}
/* Fond des selectbox */
[data-testid="stSidebar"] .stSelectbox > div > div {
    background-color: rgba(255,255,255,0.15) !important;
    border: 1px solid rgba(200,169,81,0.4) !important;
}
/* Texte dans les selectbox */
[data-testid="stSidebar"] .stSelectbox > div > div > div {
    color: #FFFFFF !important;
}
/* Option sélectionnée */
[data-testid="stSidebar"] [data-baseweb="select"] * {
    color: #FFFFFF !important;
    background-color: transparent !important;
}
/* Slider label */
[data-testid="stSidebar"] .stSlider label {
    color: #C8A951 !important;
}
/* Slider valeur */
[data-testid="stSidebar"] .stSlider [data-testid="stTickBar"] {
    color: #FFFFFF !important;
}
</style>
""", unsafe_allow_html=True)

    # Filtres optionnels dans la sidebar
    with st.sidebar:
        st.markdown("---")
        st.markdown(
            '<div style="font-size:11px;color:rgba(200,169,81,0.8);'
            'text-transform:uppercase;letter-spacing:0.06em;">'
            'Filtres chatbot</div>',
            unsafe_allow_html=True
        )
        filtre_dim = st.selectbox(
            "Dimension IF",
            ["Toutes"] + DIMENSIONS_IF,
            key="chat_dim"
        )
        filtre_zone = st.selectbox(
            "Zone",
            ["Toutes"] + ZONES_CEMAC,
            key="chat_zone"
        )
        filtre_cible = st.selectbox(
            "Cible prioritaire",
            ["Toutes"] + CIBLES_IF,
            key="chat_cible"
        )
        top_k = st.slider(
            "Nombre de sources",
            min_value=3, max_value=15, value=8,
            key="chat_topk"
        )
        if st.button("Effacer la conversation",
                     use_container_width=True):
            st.session_state["chat_historique"]  = []
            st.session_state["chat_sources"]     = []
            st.session_state["chat_suggestions"] = []
            st.rerun()

    # Afficher l'historique de conversation
    historique = st.session_state["chat_historique"]

    for msg in historique:
        if msg["role"] == "user":
            with st.chat_message(
                "user",
                avatar="👤"
            ):
                st.markdown(
                    f'<div style="font-weight:500;">'
                    f'{msg["content"]}</div>',
                    unsafe_allow_html=True
                )
        else:
            with st.chat_message(
                "assistant",
                avatar="🏦"
            ):
                st.markdown(msg["content"])

    # Afficher les sources du dernier échange
    if st.session_state["chat_sources"]:
        with st.expander(
            f"Sources ({len(st.session_state['chat_sources'])})",
            expanded=False
        ):
            for src in st.session_state["chat_sources"]:
                score_pct = int(src.get("score", 0) * 100)
                st.markdown(
                    f"**{src['source']}** — {src['titre'][:70]}  \n"
                    f"Pertinence : {score_pct}% · {src['date']}  \n"
                    f"[Lire l'article]({src['url']})"
                )
                st.markdown("---")

    # Afficher les suggestions du dernier échange
    if st.session_state["chat_suggestions"]:
        with st.expander("Recommandations DIIF", expanded=False):
            for s in st.session_state["chat_suggestions"]:
                priorite_color = {
                    "haute":  "#E74C3C",
                    "moyenne": "#E67E22",
                    "faible": "#27AE60",
                }.get(s.get("priorite", ""), "#888")
                st.markdown(
                    f'<span style="color:{priorite_color};'
                    f'font-weight:600;">●</span> '
                    f'**{s.get("titre", "")}**',
                    unsafe_allow_html=True
                )
                st.caption(s.get("description", ""))
                st.markdown("---")

    # Zone de saisie
    question = st.chat_input(
        "Posez votre question sur l'inclusion financière..."
    )

    if question and question.strip().lower() in [
        "/sources", "liste des sources",
        "quelles sont tes sources",
        "quelles sources as-tu",
        "quelles sont vos sources",
        "liste tes sources",
    ]:
        with st.chat_message("user"):
            st.write(question)
        with st.chat_message("assistant"):
            try:
                from core.database import get_db
                with get_db() as conn:
                    sources_db = conn.execute("""
                        SELECT s.nom, s.langue, s.url,
                               COUNT(a.id) as nb_articles,
                               MAX(a.collecte_le) as derniere
                        FROM sources s
                        LEFT JOIN articles a
                            ON a.source_id = s.id
                        GROUP BY s.id
                        ORDER BY nb_articles DESC
                    """).fetchall()
                sources_db   = [dict(r) for r in sources_db]
                sources_avec = [
                    s for s in sources_db
                    if s["nb_articles"] > 0
                ]
                sources_sans = [
                    s for s in sources_db
                    if s["nb_articles"] == 0
                ]
                total = sum(
                    s["nb_articles"] for s in sources_db
                )
                reponse_sources = (
                    f"Ma base documentaire contient "
                    f"**{total} articles** issus de "
                    f"**{len(sources_avec)} sources "
                    f"alimentées** :\n\n"
                )
                for src in sources_avec:
                    derniere = (src["derniere"] or "")[:10]
                    reponse_sources += (
                        f"- **{src['nom']}** "
                        f"({src['langue'].upper()}) — "
                        f"{src['nb_articles']} article(s)"
                        f"{' · ' + derniere if derniere else ''}\n"
                    )
                if sources_sans:
                    reponse_sources += (
                        f"\n{len(sources_sans)} source(s) "
                        f"configurée(s) sans articles "
                        f"collectés : "
                        + ", ".join(
                            s["nom"] for s in sources_sans
                        )
                    )
            except Exception as e:
                reponse_sources = f"Erreur : {e}"

            st.write(reponse_sources)

        st.session_state["chat_historique"].append(
            {"role": "user", "content": question}
        )
        st.session_state["chat_historique"].append(
            {"role": "assistant",
             "content": reponse_sources}
        )
        st.rerun()

    elif question:
        # Afficher la question immédiatement
        with st.chat_message("user"):
            st.write(question)

        # Préparer les filtres
        dim   = None if filtre_dim   == "Toutes" else filtre_dim
        zone  = None if filtre_zone  == "Toutes" else filtre_zone
        cible = None if filtre_cible == "Toutes" else filtre_cible

        # Lancer l'orchestrateur
        with st.chat_message("assistant", avatar="🏦"):
            sources     = []
            suggestions = []
            reponse     = ""

            try:
                from agents.svia_agent import orchestrer

                # Phase 1 — tool calls + métadonnées (spinner visible)
                with st.spinner("🔍 Recherche en cours..."):
                    result = orchestrer(
                        question=question,
                        historique=historique,
                        dimension=dim,
                        zone=zone,
                        cible=cible,
                        top_k=top_k,
                        stream=True,
                    )
                    sources     = result.get("sources", [])
                    suggestions = result.get("suggestions", [])

                # Phase 2 — affichage du texte
                reponse_data = result.get("reponse", "")
                placeholder  = st.empty()

                if hasattr(reponse_data, "__iter__") and not isinstance(reponse_data, str):
                    # Streaming token par token
                    reponse_acc = ""
                    for token in reponse_data:
                        reponse_acc += token
                        placeholder.markdown(reponse_acc + " ▌")
                    placeholder.markdown(reponse_acc)
                    reponse = reponse_acc
                else:
                    # Retour direct (salutation, guardrail, hors périmètre)
                    reponse = str(reponse_data) if reponse_data else ""
                    placeholder.markdown(reponse)

            except Exception as e:
                reponse = f"Erreur : {e}"
                st.markdown(reponse)

            st.markdown(
                '<div style="font-size:10px;color:#C8A951;'
                'margin-top:8px;font-style:italic;">'
                '— Systeme de veille DIIF/BEAC</div>',
                unsafe_allow_html=True
            )

            try:
                from core.database import get_db
                with get_db() as conn:
                    dates = conn.execute("""
                        SELECT MIN(publie_le), MAX(publie_le)
                        FROM articles
                        WHERE publie_le IS NOT NULL
                    """).fetchone()
                if dates and dates[0]:
                    st.caption(
                        f"Reponse basee sur {len(sources)} source(s) · "
                        f"Publications entre "
                        f"{(dates[0] or '')[:10]} et "
                        f"{(dates[1] or '')[:10]}"
                    )
            except Exception:
                pass

            col_fb1, col_fb2, _ = st.columns([1, 1, 8])
            with col_fb1:
                if st.button("👍", key=f"fb_ok_{len(historique)}",
                             help="Reponse utile"):
                    pass
            with col_fb2:
                if st.button("👎", key=f"fb_ko_{len(historique)}",
                             help="Reponse a ameliorer"):
                    pass

        # Mettre à jour l'historique
        st.session_state["chat_historique"].append(
            {"role": "user",      "content": question}
        )
        st.session_state["chat_historique"].append(
            {"role": "assistant", "content": reponse}
        )
        st.session_state["chat_sources"]     = sources
        st.session_state["chat_suggestions"] = suggestions

        st.rerun()
