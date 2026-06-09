"""
ui/pages/suggestions_page.py — Page Suggestions DIIF
Recommandations organisées par priorité et dimension,
historique des actions DIIF, interface d'alimentation.
"""
import streamlit as st
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
from core.database import (get_actions_diif, sauvegarder_action_diif,
                            get_db, new_id, now_iso)
from config import DIMENSIONS_IF, ZONES_CEMAC


def render_suggestions(user):
    st.title("Suggestions")
    st.caption(
        "Recommandations générées à partir de l'actualité mondiale "
        "et croisées avec l'historique des actions DIIF."
    )

    tab1, tab2, tab3 = st.tabs([
        "Générer des suggestions",
        "Historique DIIF",
        "Enregistrer une action",
    ])

    # ── TAB 1 : Générer des suggestions ──────────────────────────
    with tab1:
        st.subheader("Générer des recommandations")

        col1, col2 = st.columns(2)
        with col1:
            dimension = st.selectbox(
                "Dimension IF",
                ["Toutes"] + DIMENSIONS_IF,
                key="sug_dim"
            )
        with col2:
            zone = st.selectbox(
                "Zone géographique",
                ["Toutes"] + ZONES_CEMAC,
                key="sug_zone"
            )

        question = st.text_area(
            "Contexte ou question spécifique (optionnel)",
            placeholder=(
                "Ex : Quelles actions le DIIF pourrait-il mener "
                "pour améliorer l'accès au crédit des femmes "
                "entrepreneures en zone rurale ?"
            ),
            height=100,
            key="sug_question"
        )

        if st.button(
            "Générer les recommandations",
            use_container_width=True,
            key="btn_generer_sug"
        ):
            dim_val  = None if dimension == "Toutes" else dimension
            zone_val = None if zone == "Toutes" else zone
            q = question.strip() or (
                f"Quelles sont les meilleures pratiques mondiales "
                f"en matière d'inclusion financière"
                f"{' pour ' + dim_val if dim_val else ''}"
                f"{' en ' + zone_val if zone_val else ''} ?"
            )

            with st.spinner("Analyse en cours..."):
                try:
                    from agents.svia_agent import orchestrer
                    result = orchestrer(
                        question=q,
                        dimension=dim_val or None,
                        top_k=8,
                    )
                    st.session_state["suggestions_generees"] = result.get("suggestions", [])

                except Exception as e:
                    st.error(f"Erreur : {e}")

        # Affichage des suggestions
        if "suggestions_generees" in st.session_state:
            suggestions = st.session_state["suggestions_generees"]
            if not suggestions:
                st.info("Aucune recommandation générée.")
            else:
                st.markdown("---")
                st.subheader(
                    f"{len(suggestions)} recommandation(s)"
                )
                for s in suggestions:
                    priorite = s.get("priorite", "moyenne")
                    couleur  = {
                        "haute":  "#E74C3C",
                        "moyenne": "#E67E22",
                        "faible": "#27AE60",
                    }.get(priorite, "#888")
                    dim_s = s.get("dimension", "")

                    st.markdown(
                        f'<div style="border-left:4px solid {couleur};'
                        f'padding:0.75rem 1rem;margin-bottom:1rem;'
                        f'background:#fafafa;border-radius:0 8px 8px 0;">'
                        f'<div style="font-weight:600;color:#002B5C;">'
                        f'{s.get("titre","")}</div>'
                        f'<div style="font-size:12px;color:{couleur};'
                        f'margin:4px 0;">Priorité : {priorite.upper()}'
                        f'{" · " + dim_s if dim_s else ""}</div>'
                        f'<div style="font-size:13px;color:#444;">'
                        f'{s.get("description","")}</div>'
                        f'</div>',
                        unsafe_allow_html=True
                    )

                    # Bouton pour enregistrer comme action DIIF
                    if st.button(
                        "Enregistrer comme action DIIF",
                        key=f"save_sug_{suggestions.index(s)}"
                    ):
                        action = {
                            "id":           new_id(),
                            "titre":        s.get("titre", ""),
                            "description":  s.get("description", ""),
                            "dimension":    s.get("dimension"),
                            "zone":         zone_val,
                            "date_action":  now_iso()[:10],
                            "statut":       "planifié",
                            "source_info":  "Généré par le système de veille",
                            "cree_par":     user["id"],
                            "cree_le":      now_iso(),
                        }
                        if sauvegarder_action_diif(action):
                            st.success("Action enregistrée.")
                        else:
                            st.error("Erreur lors de l'enregistrement.")

    # ── TAB 2 : Historique DIIF ───────────────────────────────────
    with tab2:
        st.subheader("Historique des actions DIIF")

        filtre_dim = st.selectbox(
            "Filtrer par dimension",
            ["Toutes"] + DIMENSIONS_IF,
            key="hist_dim"
        )
        dim_filtre = (
            None if filtre_dim == "Toutes" else filtre_dim
        )

        actions = get_actions_diif(dim_filtre, limit=50)

        if not actions:
            st.info(
                "Aucune action enregistrée. "
                "Utilisez l'onglet 'Enregistrer une action' "
                "pour commencer."
            )
        else:
            statut_couleur = {
                "réalisé":  "#27AE60",
                "en cours": "#E67E22",
                "planifié": "#3498DB",
            }
            for action in actions:
                statut  = action.get("statut", "réalisé")
                couleur = statut_couleur.get(statut, "#888")
                st.markdown(
                    f'<div style="border-left:4px solid {couleur};'
                    f'padding:0.6rem 1rem;margin-bottom:0.75rem;'
                    f'background:#fafafa;border-radius:0 8px 8px 0;">'
                    f'<div style="font-weight:600;color:#002B5C;">'
                    f'{action["titre"]}</div>'
                    f'<div style="font-size:11px;color:{couleur};">'
                    f'{statut.upper()} · '
                    f'{action.get("dimension","") or "Général"} · '
                    f'{(action.get("date_action",""))[:10]}'
                    f'</div>'
                    f'<div style="font-size:12px;color:#555;margin-top:4px;">'
                    f'{action.get("description","")[:200]}'
                    f'</div>'
                    f'</div>',
                    unsafe_allow_html=True
                )

    # ── TAB 3 : Enregistrer une action ────────────────────────────
    with tab3:
        st.subheader("Enregistrer une action DIIF")
        st.caption(
            "Documentez les actions passées, en cours ou planifiées "
            "du DIIF pour enrichir les recommandations futures."
        )

        with st.form("form_action_diif"):
            titre = st.text_input(
                "Titre de l'action *",
                placeholder="Ex : Atelier de sensibilisation mobile money"
            )
            description = st.text_area(
                "Description *",
                placeholder=(
                    "Décrivez l'action, ses objectifs et ses résultats..."
                ),
                height=120
            )
            col1, col2 = st.columns(2)
            with col1:
                dimension = st.selectbox(
                    "Dimension IF",
                    ["—"] + DIMENSIONS_IF,
                    key="form_action_dim"
                )
                date_action = st.date_input(
                    "Date de l'action"
                )
            with col2:
                zone = st.selectbox(
                    "Zone concernée",
                    ["—"] + ZONES_CEMAC,
                    key="form_action_zone"
                )
                statut = st.selectbox(
                    "Statut",
                    ["réalisé", "en cours", "planifié"]
                )
            source_info = st.text_input(
                "Source / référence (optionnel)",
                placeholder="Ex : Rapport atelier DIIF 2025"
            )
            submitted = st.form_submit_button(
                "Enregistrer",
                use_container_width=True
            )

        if submitted:
            if not titre or not description:
                st.error("Le titre et la description sont obligatoires.")
            else:
                action = {
                    "id":          new_id(),
                    "titre":       titre,
                    "description": description,
                    "dimension":   None if dimension == "—" else dimension,
                    "zone":        None if zone == "—" else zone,
                    "date_action": str(date_action),
                    "statut":      statut,
                    "source_info": source_info or None,
                    "cree_par":    user["id"],
                    "cree_le":     now_iso(),
                }
                if sauvegarder_action_diif(action):
                    st.success("Action enregistrée avec succès.")
                    st.rerun()
                else:
                    st.error("Erreur lors de l'enregistrement.")
