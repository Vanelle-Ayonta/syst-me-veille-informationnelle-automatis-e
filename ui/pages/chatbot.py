"""
ui/pages/chatbot.py — Interface du chatbot DIIF
Chatbot conversationnel avec historique de session,
sources citées et suggestions actionnables.
"""
import streamlit as st
import sys, os, html
sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
# (filtres dimension/zone/cible retirés du chatbot — conservés côté Veille)

# Marqueurs de rôle injectés dans chaque message — pilotent le style des bulles
# (CSS :has(...) dans app.py), indépendamment des data-testid internes Streamlit.
_MARQUEUR_USER = '<span class="svia-role svia-role-user"></span>'
_MARQUEUR_BOT  = '<span class="svia-role svia-role-bot svia-marker-hide"></span>'


def _msg_user(contenu: str):
    """Affiche un message utilisateur (bulle bleue, à droite)."""
    with st.chat_message("user", avatar="👤"):
        st.markdown(
            f'{_MARQUEUR_USER}<div style="font-weight:500;">'
            f'{html.escape(contenu)}</div>',
            unsafe_allow_html=True,
        )


def _msg_bot(contenu: str):
    """Affiche un message SVIA (bulle crème, à gauche), contenu en markdown."""
    with st.chat_message("assistant", avatar="🏦"):
        st.markdown(_MARQUEUR_BOT, unsafe_allow_html=True)
        st.markdown(contenu)


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
    if "chat_last_interaction_id" not in st.session_state:
        st.session_state["chat_last_interaction_id"] = None
    if "chat_feedback" not in st.session_state:
        st.session_state["chat_feedback"] = {}

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

    # Paramètres du chatbot dans la sidebar
    with st.sidebar:
        st.markdown("---")
        st.markdown(
            '<div style="font-size:11px;color:rgba(200,169,81,0.8);'
            'text-transform:uppercase;letter-spacing:0.06em;">'
            'Chatbot</div>',
            unsafe_allow_html=True
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
            st.session_state["chat_last_interaction_id"] = None
            st.session_state["chat_feedback"]    = {}
            st.rerun()

    # Afficher l'historique de conversation
    historique = st.session_state["chat_historique"]

    for msg in historique:
        if msg["role"] == "user":
            _msg_user(msg["content"])
        else:
            _msg_bot(msg["content"])

    # Feedback sur la dernière réponse (👍/👎) — écriture immédiate au clic.
    # Placé dans la zone persistante (après rerun) pour rester cliquable.
    last_iid = st.session_state.get("chat_last_interaction_id")
    if (last_iid and historique and historique[-1]["role"] == "assistant"):
        note_donnee = st.session_state["chat_feedback"].get(last_iid)
        if note_donnee == 1:
            st.caption("✅ Merci pour votre retour positif.")
        elif note_donnee == -1:
            st.caption("✅ Merci, votre retour a été pris en compte.")
        else:
            st.caption("Cette réponse vous a-t-elle été utile ?")
            cfb1, cfb2, _ = st.columns([1, 1, 8])
            from core.database import enregistrer_feedback
            with cfb1:
                if st.button("👍", key=f"fb_ok_{last_iid}",
                             help="Réponse utile"):
                    enregistrer_feedback(last_iid, 1,
                                         utilisateur_id=user.get("id"))
                    st.session_state["chat_feedback"][last_iid] = 1
                    st.rerun()
            with cfb2:
                if st.button("👎", key=f"fb_ko_{last_iid}",
                             help="Réponse à améliorer"):
                    enregistrer_feedback(last_iid, -1,
                                         utilisateur_id=user.get("id"))
                    st.session_state["chat_feedback"][last_iid] = -1
                    st.rerun()

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
        _msg_user(question)
        with st.chat_message("assistant", avatar="🏦"):
            st.markdown(_MARQUEUR_BOT, unsafe_allow_html=True)
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
        _msg_user(question)

        # Lancer l'orchestrateur
        with st.chat_message("assistant", avatar="🏦"):
            st.markdown(_MARQUEUR_BOT, unsafe_allow_html=True)
            sources     = []
            reponse     = ""
            result      = {}

            # Indicateur animé « SVIA rédige… » — visible dès maintenant et
            # pendant toute l'attente (retrieval + 1er token). Animation CSS
            # pure : tourne côté navigateur même quand Python attend.
            placeholder = st.empty()
            _INDICATEUR = (
                '<div class="svia-typing">'
                '<span class="svia-dot"></span>'
                '<span class="svia-dot"></span>'
                '<span class="svia-dot"></span>'
                ' <em>SVIA rédige…</em></div>'
            )
            placeholder.markdown(_INDICATEUR, unsafe_allow_html=True)

            try:
                from agents.svia_agent import orchestrer

                result = orchestrer(
                    question=question,
                    historique=historique,
                    top_k=top_k,
                    stream=True,
                    utilisateur_id=user.get("id"),
                )
                sources     = result.get("sources", [])
                reponse_data = result.get("reponse", "")

                if hasattr(reponse_data, "__iter__") and not isinstance(reponse_data, str):
                    # Streaming token par token avec curseur clignotant.
                    # On échappe < et > pour neutraliser tout HTML pendant le
                    # streaming (le rendu final repasse en markdown sûr).
                    # Le 1er token remplace l'indicateur (overwrite du placeholder)
                    reponse_acc = ""
                    for token in reponse_data:
                        reponse_acc += token
                        affichage = (
                            reponse_acc.replace("<", "&lt;").replace(">", "&gt;")
                        )
                        placeholder.markdown(
                            affichage + '<span class="svia-cursor"></span>',
                            unsafe_allow_html=True,
                        )
                    # Rendu final propre (markdown complet, sans curseur)
                    placeholder.markdown(reponse_acc)
                    reponse = reponse_acc
                else:
                    # Retour direct (salutation, guardrail, hors périmètre)
                    reponse = str(reponse_data) if reponse_data else ""
                    placeholder.markdown(reponse)

            except Exception as e:
                reponse = f"Erreur : {e}"
                placeholder.markdown(reponse)

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

        # Mettre à jour l'historique
        st.session_state["chat_historique"].append(
            {"role": "user",      "content": question}
        )
        st.session_state["chat_historique"].append(
            {"role": "assistant", "content": reponse}
        )
        st.session_state["chat_sources"]     = sources
        # Suggestions différées : générées en parallèle, prêtes à la fin du flux.
        st.session_state["chat_suggestions"] = result.get("suggestions", [])
        # Conserve l'id d'interaction pour le feedback (boutons 👍/👎 persistants)
        st.session_state["chat_last_interaction_id"] = result.get("interaction_id")

        st.rerun()
