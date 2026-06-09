"""
ui/pages/dashboard.py — Tableau de bord amélioré
Métriques, graphiques temporels, répartition par source/langue,
alertes nouvelles publications.
"""
import streamlit as st
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
from core.database import get_stats_dashboard, get_db
from config import DIMENSIONS_IF


@st.cache_data(ttl=300)
def _stats_cached():
    return get_stats_dashboard()


@st.cache_data(ttl=300)
def _couverture_cached():
    """Compte les articles par dimension IF en une seule connexion."""
    with get_db() as conn:
        result = {}
        for dim in DIMENSIONS_IF:
            kw = dim.lower()[:8]
            result[dim] = conn.execute(
                "SELECT COUNT(*) FROM articles a "
                "WHERE LOWER(a.contenu) LIKE ? OR LOWER(a.titre) LIKE ?",
                (f"%{kw}%", f"%{kw}%")
            ).fetchone()[0]
    return result


@st.cache_data(ttl=60)
def _recents_cached():
    with get_db() as conn:
        rows = conn.execute("""
            SELECT a.titre, a.url_original,
                   a.collecte_le, a.langue,
                   s.nom as source
            FROM articles a
            JOIN sources s ON a.source_id = s.id
            ORDER BY a.collecte_le DESC
            LIMIT 10
        """).fetchall()
    return [dict(r) for r in rows]


def render_dashboard(user):
    st.title("Tableau de bord")
    st.caption(
        f"Bienvenue, {user['nom']} · "
        f"{user['role'].capitalize()}"
    )

    stats = _stats_cached()

    # ── Métriques principales ──────────────────────────────────────
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown("""
        <div style="background:#ffffff;border-radius:10px;
                    padding:16px 20px;border-left:4px solid #002B5C;
                    box-shadow:0 2px 8px rgba(0,0,0,0.06);">
            <div style="font-size:11px;color:#888;font-weight:600;
                        text-transform:uppercase;letter-spacing:0.06em;">
                Articles collectés
            </div>
            <div style="font-size:32px;font-weight:700;color:#002B5C;
                        margin-top:4px;">
        """ + str(stats["total_articles"]) + """
            </div>
            <div style="font-size:11px;color:#C8A951;margin-top:2px;">
                📰 Corpus total
            </div>
        </div>
        """, unsafe_allow_html=True)

    with col2:
        st.markdown("""
        <div style="background:#ffffff;border-radius:10px;
                    padding:16px 20px;border-left:4px solid #C8A951;
                    box-shadow:0 2px 8px rgba(0,0,0,0.06);">
            <div style="font-size:11px;color:#888;font-weight:600;
                        text-transform:uppercase;letter-spacing:0.06em;">
                Documents internes
            </div>
            <div style="font-size:32px;font-weight:700;color:#002B5C;
                        margin-top:4px;">
        """ + str(stats["total_docs"]) + """
            </div>
            <div style="font-size:11px;color:#C8A951;margin-top:2px;">
                📁 Uploadés
            </div>
        </div>
        """, unsafe_allow_html=True)

    with col3:
        st.markdown("""
        <div style="background:#ffffff;border-radius:10px;
                    padding:16px 20px;border-left:4px solid #27AE60;
                    box-shadow:0 2px 8px rgba(0,0,0,0.06);">
            <div style="font-size:11px;color:#888;font-weight:600;
                        text-transform:uppercase;letter-spacing:0.06em;">
                Sources actives
            </div>
            <div style="font-size:32px;font-weight:700;color:#002B5C;
                        margin-top:4px;">
        """ + str(stats["sources_actives"]) + """
            </div>
            <div style="font-size:11px;color:#27AE60;margin-top:2px;">
                🌐 En collecte
            </div>
        </div>
        """, unsafe_allow_html=True)

    with col4:
        derniere = (stats["derniere_collecte"] or "—")[:10]
        st.markdown(f"""
        <div style="background:#ffffff;border-radius:10px;
                    padding:16px 20px;border-left:4px solid #3498DB;
                    box-shadow:0 2px 8px rgba(0,0,0,0.06);">
            <div style="font-size:11px;color:#888;font-weight:600;
                        text-transform:uppercase;letter-spacing:0.06em;">
                Dernière collecte
            </div>
            <div style="font-size:22px;font-weight:700;color:#002B5C;
                        margin-top:4px;">
                {derniere}
            </div>
            <div style="font-size:11px;color:#3498DB;margin-top:2px;">
                🕐 Mise à jour
            </div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<div style='height:16px'></div>",
                unsafe_allow_html=True)

    # ── Stats RAG ─────────────────────────────────────────────────

    st.markdown("---")

    # ── Graphique évolution temporelle ────────────────────────────
    if stats["par_mois"]:
        st.subheader("Évolution de la collecte")
        import plotly.graph_objects as go

        donnees = list(reversed(stats["par_mois"]))
        mois    = [r["mois"]  for r in donnees]
        nbarts  = [r["nb"]    for r in donnees]

        if len(mois) == 1:
            st.metric(
                f"Articles collectés en {mois[0]}",
                nbarts[0]
            )
            st.caption(
                "Le graphique d'évolution s'affichera "
                "après plusieurs mois de collecte."
            )
        else:
            fig = go.Figure()
            fig.add_trace(go.Bar(
                x=mois, y=nbarts,
                marker_color="#002B5C",
                name="Articles collectés",
                text=nbarts,
                textposition="outside",
            ))
            fig.add_trace(go.Scatter(
                x=mois, y=nbarts,
                mode="lines+markers",
                line=dict(color="#C8A951", width=2),
                marker=dict(size=7, color="#C8A951"),
                name="Tendance",
            ))
            fig.update_layout(
                height=320,
                margin=dict(l=0, r=0, t=20, b=0),
                plot_bgcolor="white",
                paper_bgcolor="white",
                legend=dict(orientation="h", yanchor="bottom", y=1.02),
                xaxis=dict(showgrid=False, type="category"),
                yaxis=dict(gridcolor="#f0f0f0"),
                bargap=0.3,
            )
            st.plotly_chart(fig, use_container_width=True)
    else:
        st.subheader("Évolution de la collecte")
        st.info(
            "Aucun article en base. "
            "Lancez la collecte depuis Veille & filtres."
        )

    st.markdown("---")

    # ── Répartition par source et langue ─────────────────────────
    col_src, col_lang = st.columns(2)

    with col_src:
        st.subheader("Articles par source")
        if stats["par_source"]:
            import plotly.express as px
            sources = stats["par_source"]
            fig2 = px.bar(
                x=[s["nb"]  for s in sources],
                y=[s["nom"] for s in sources],
                orientation="h",
                color_discrete_sequence=["#002B5C"],
            )
            fig2.update_layout(
                height=350,
                margin=dict(l=0, r=0, t=10, b=0),
                xaxis_title="",
                yaxis_title="",
                plot_bgcolor="white",
                paper_bgcolor="white",
                xaxis=dict(gridcolor="#f0f0f0"),
                yaxis=dict(showgrid=False),
            )
            st.plotly_chart(fig2, use_container_width=True)

    with col_lang:
        st.subheader("Répartition par langue")
        if stats["par_langue"]:
            import plotly.express as px
            langues = stats["par_langue"]
            fig3 = px.pie(
                values=[l["nb"]     for l in langues],
                names=[l["langue"]  for l in langues],
                color_discrete_sequence=["#002B5C", "#C8A951",
                                          "#4A90D9", "#E8E8E8"],
                hole=0.4,
            )
            fig3.update_layout(
                height=350,
                margin=dict(l=0, r=0, t=10, b=0),
                paper_bgcolor="white",
            )
            st.plotly_chart(fig3, use_container_width=True)

    st.markdown("---")

    # ── Couverture par dimension IF ───────────────────────────────
    st.subheader("Couverture par dimension")
    couverture = _couverture_cached()
    cols = st.columns(3)
    for i, dim in enumerate(DIMENSIONS_IF):
        with cols[i % 3]:
            st.metric(dim, f"{couverture.get(dim, 0)} extraits")

    st.markdown("---")

    # ── Alertes — derniers articles collectés ─────────────────────
    st.subheader("Dernières publications")
    recents = _recents_cached()
    for art in recents:
        col1, col2 = st.columns([5, 1])
        with col1:
            titre = (art["titre"] or "")[:80]
            st.markdown(f"**{art['source']}** — {titre}")
            st.caption(
                f"Collecté le {(art['collecte_le'] or '')[:10]} · "
                f"{(art['langue'] or '').upper()}"
            )
        with col2:
            if art["url_original"]:
                st.markdown(
                    f"[Lire]({art['url_original']})",
                    unsafe_allow_html=False
                )
