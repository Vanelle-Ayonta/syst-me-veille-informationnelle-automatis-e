"""
ui/pages/logs.py — Journal d'activité avec filtres
"""
import streamlit as st
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
from core.database import get_db


def render_logs(user):
    st.title("Logs d'activité")
    st.caption("Journal complet des actions effectuées sur le système.")

    # Filtres
    col1, col2, col3 = st.columns(3)
    with col1:
        filtre_action = st.text_input(
            "Filtrer par action",
            placeholder="Ex : COLLECTE, USER, LOGIN..."
        )
    with col2:
        filtre_user = st.text_input(
            "Filtrer par utilisateur",
            placeholder="Nom ou email"
        )
    with col3:
        filtre_date = st.date_input(
            "Depuis le",
            value=None,
            key="logs_date"
        )

    limit = st.selectbox(
        "Afficher",
        [50, 100, 200, 500],
        key="logs_limit"
    )

    # Requête — table logs_activite
    with get_db() as conn:
        query = """
            SELECT l.id, l.action,
                   l.entite_type as entite,
                   l.detail,
                   l.horodatage as date_action,
                   u.nom   as user_nom,
                   u.email as user_email
            FROM logs_activite l
            LEFT JOIN utilisateurs u ON l.utilisateur_id = u.id
            WHERE 1=1
        """
        params = []

        if filtre_action:
            query  += " AND UPPER(l.action) LIKE ?"
            params.append(f"%{filtre_action.upper()}%")
        if filtre_user:
            query  += (
                " AND (u.nom LIKE ? OR u.email LIKE ?)"
            )
            params += [
                f"%{filtre_user}%",
                f"%{filtre_user}%"
            ]
        if filtre_date:
            query  += " AND DATE(l.horodatage) >= ?"
            params.append(str(filtre_date))

        query += " ORDER BY l.horodatage DESC LIMIT ?"
        params.append(limit)

        logs = conn.execute(query, params).fetchall()
        logs = [dict(r) for r in logs]

    st.caption(f"{len(logs)} entrée(s) trouvée(s)")

    if not logs:
        st.info("Aucun log trouvé.")
        return

    # Couleurs par type d'action
    def couleur_action(action: str) -> str:
        action = action.upper()
        if "ERREUR" in action or "FAILED" in action or "ECHEC" in action:
            return "#E74C3C"
        if "LOGIN" in action or "CONNEXION" in action:
            return "#3498DB"
        if "COLLECTE" in action or "SCRAPING" in action:
            return "#27AE60"
        if "USER" in action:
            return "#9B59B6"
        if "EXPORT" in action or "EMAIL" in action:
            return "#E67E22"
        return "#888888"

    for log_entry in logs:
        couleur     = couleur_action(log_entry["action"])
        date        = (log_entry.get("date_action") or "")[:19]
        nom         = log_entry.get("user_nom") or "Système"
        detail      = log_entry.get("detail") or ""
        detail_html = (
            f'<br><span style="font-size:11px;color:#666;">'
            f'{detail[:120]}</span>'
            if detail else ""
        )

        st.markdown(
            f'<div style="border-left:3px solid {couleur};'
            f'padding:6px 12px;margin-bottom:4px;'
            f'background:#fafafa;border-radius:0 6px 6px 0;">'
            f'<span style="color:{couleur};font-weight:600;'
            f'font-size:12px;">{log_entry["action"]}</span>'
            f'<span style="color:#888;font-size:11px;'
            f'margin-left:8px;">{date}</span>'
            f'<span style="color:#555;font-size:11px;'
            f'margin-left:8px;">— {nom}</span>'
            f'{detail_html}'
            f'</div>',
            unsafe_allow_html=True
        )