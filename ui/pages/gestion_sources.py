import streamlit as st
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
from core.database import (get_all_sources, create_source,
                            toggle_source, delete_source, log_action)

def render_sources(user):
    st.title("Gestion des sources")

    with st.expander("Ajouter une source"):
        with st.form("form_add_source"):
            nom      = st.text_input("Nom de la source")
            url      = st.text_input("URL (flux RSS ou page web)")
            type_src = st.selectbox("Type", ["rss", "web"])
            langue   = st.selectbox("Langue", ["fr", "en"])
            freq     = st.number_input(
                "Fréquence de collecte (heures)",
                value=168, min_value=1, step=1
            )
            if st.form_submit_button("Ajouter", use_container_width=True):
                if not nom or not url:
                    st.error("Nom et URL requis.")
                else:
                    create_source(nom, url, type_src, langue, int(freq), user["id"])
                    log_action(user["id"], "SOURCE_AJOUTEE", detail=nom)
                    st.success(f"Source « {nom} » ajoutée.")
                    st.rerun()

    st.markdown("---")
    sources = get_all_sources()
    if not sources:
        st.info("Aucune source enregistrée.")
        return

    actives   = [s for s in sources if s["active"]]
    inactives = [s for s in sources if not s["active"]]

    st.subheader(f"Sources actives ({len(actives)})")
    for src in actives:
        _render_source_row(src, user)

    if inactives:
        st.markdown("---")
        st.subheader(f"Sources inactives ({len(inactives)})")
        for src in inactives:
            _render_source_row(src, user)


def _render_source_row(src, user):
    col1, col2, col3 = st.columns([5, 1, 1])
    with col1:
        dc = src["derniere_collecte"][:10] if src.get("derniere_collecte") else "jamais"
        st.markdown(f"**{src['nom']}** — `{src['type_source']}` · {src['langue'].upper()}")
        st.caption(f"{src['url']} · Dernière collecte : {dc} · Fréquence : {src['frequence_heures']}h")
    with col2:
        label = "Désactiver" if src["active"] else "Activer"
        if st.button(label, key=f"tog_{src['id']}"):
            toggle_source(src["id"], not src["active"])
            log_action(user["id"], "SOURCE_MAJ", detail=src["nom"])
            st.rerun()
    with col3:
        if st.button("Supprimer", key=f"del_{src['id']}"):
            delete_source(src["id"])
            log_action(user["id"], "SOURCE_SUPPRIMEE", detail=src["nom"])
            st.rerun()
