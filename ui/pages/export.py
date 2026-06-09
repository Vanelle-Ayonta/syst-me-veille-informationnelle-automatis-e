"""
ui/pages/export.py — Page Export DIIF/BEAC
Génération et téléchargement des rapports Word/PDF,
envoi du bulletin par email.
"""
import streamlit as st
import sys, os
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
from config import DIMENSIONS_IF


def render_export(user):
    st.title("Exporter")
    st.caption(
        "Générez et téléchargez le bulletin de veille "
        "ou envoyez-le par email."
    )

    tab1, tab2 = st.tabs([
        "Générer le rapport",
        "Envoyer par email",
    ])

    # ── TAB 1 : Générer le rapport ────────────────────────────────
    with tab1:
        st.subheader("Paramètres du rapport")

        col1, col2 = st.columns(2)
        with col1:
            jours = st.selectbox(
                "Période couverte",
                [7, 14, 30, 60, 90],
                format_func=lambda x: f"{x} derniers jours",
                key="export_jours"
            )
        with col2:
            avec_reco = st.checkbox(
                "Inclure les recommandations DIIF",
                value=True,
                key="export_reco"
            )

        st.markdown("---")

        # Aperçu des données disponibles
        try:
            from core.export import get_articles_periode
            donnees = get_articles_periode(jours)
            col_a, col_b, col_c = st.columns(3)
            col_a.metric("Articles disponibles", donnees["total"])
            col_b.metric("Sources", len(donnees["sources"]))
            col_c.metric(
                "Période",
                f"{donnees['depuis']} → {donnees['jusqu']}"
            )
        except Exception as e:
            st.warning(f"Aperçu non disponible : {e}")

        st.markdown("---")

        col_word, col_pdf = st.columns(2)

        # ── Export Word ──────────────────────────────────────────
        with col_word:
            st.subheader("Format Word (.docx)")
            st.caption(
                "Rapport complet avec mise en forme "
                "institutionnelle BEAC."
            )
            if st.button(
                "Générer le rapport Word",
                use_container_width=True,
                key="btn_word"
            ):
                with st.spinner(
                    "Génération en cours — "
                    "synthèse éditoriale par Claude..."
                ):
                    try:
                        from core.export import generer_rapport_word
                        word_bytes = generer_rapport_word(
                            jours=jours,
                            avec_recommandations=avec_reco,
                        )
                        st.session_state["word_bytes"] = word_bytes
                        st.success("Rapport Word généré.")
                    except Exception as e:
                        st.error(f"Erreur : {e}")

            if "word_bytes" in st.session_state:
                nom = (
                    f"Bulletin_Veille_DIIF_"
                    f"{datetime.utcnow().strftime('%Y%m%d')}.docx"
                )
                st.download_button(
                    label="Télécharger le Word",
                    data=st.session_state["word_bytes"],
                    file_name=nom,
                    mime=(
                        "application/vnd.openxmlformats-"
                        "officedocument.wordprocessingml.document"
                    ),
                    use_container_width=True,
                    key="dl_word"
                )

        # ── Export PDF ───────────────────────────────────────────
        with col_pdf:
            st.subheader("Format PDF")
            st.caption(
                "Rapport PDF directement téléchargeable."
            )
            if st.button(
                "Générer le rapport PDF",
                use_container_width=True,
                key="btn_pdf"
            ):
                with st.spinner(
                    "Génération en cours — "
                    "synthèse éditoriale par Claude..."
                ):
                    try:
                        from core.export import generer_rapport_pdf
                        pdf_bytes = generer_rapport_pdf(jours=jours)
                        st.session_state["pdf_bytes"] = pdf_bytes
                        st.success("Rapport PDF généré.")
                    except Exception as e:
                        st.error(f"Erreur : {e}")

            if "pdf_bytes" in st.session_state:
                nom_pdf = (
                    f"Bulletin_Veille_DIIF_"
                    f"{datetime.utcnow().strftime('%Y%m%d')}.pdf"
                )
                st.download_button(
                    label="Télécharger le PDF",
                    data=st.session_state["pdf_bytes"],
                    file_name=nom_pdf,
                    mime="application/pdf",
                    use_container_width=True,
                    key="dl_pdf"
                )

    # ── TAB 2 : Envoyer par email ─────────────────────────────────
    with tab2:
        if user["role"] != "administrateur":
            st.info(
                "L'envoi par email est réservé "
                "à l'administrateur."
            )
            return

        st.subheader("Envoi du bulletin par email")

        try:
            from core.database import get_db
            with get_db() as conn:
                admins = conn.execute("""
                    SELECT nom, email FROM utilisateurs
                    WHERE role = 'administrateur'
                      AND email IS NOT NULL
                """).fetchall()
            st.markdown("**Destinataires automatiques (admins) :**")
            for a in admins:
                st.markdown(f"- {a['nom']} — `{a['email']}`")
        except Exception:
            pass

        extra_env = os.getenv("MAIL_EXTRA_DESTINATAIRES", "")
        if extra_env:
            st.markdown("**Destinataires supplémentaires (.env) :**")
            for e in extra_env.split(","):
                if e.strip():
                    st.markdown(f"- `{e.strip()}`")

        st.markdown("---")

        col1, col2 = st.columns(2)
        with col1:
            jours_mail = st.selectbox(
                "Période du bulletin",
                [7, 14, 30],
                format_func=lambda x: f"{x} derniers jours",
                key="mail_jours"
            )
        with col2:
            emails_extra = st.text_input(
                "Emails supplémentaires (séparés par des virgules)",
                placeholder="email1@example.com, email2@example.com",
                key="mail_extra"
            )

        st.markdown("---")

        if st.button(
            "Envoyer le bulletin maintenant",
            use_container_width=True,
            key="btn_envoyer_mail"
        ):
            extra_list = [
                e.strip()
                for e in emails_extra.split(",")
                if e.strip()
            ] if emails_extra else []

            with st.spinner("Génération et envoi en cours..."):
                try:
                    from core.export import envoyer_bulletin_email
                    result = envoyer_bulletin_email(
                        jours=jours_mail,
                        destinataires_extra=extra_list,
                    )
                    if result["success"]:
                        st.success(
                            f"Bulletin envoyé à "
                            f"{len(result['envoyes'])} "
                            f"destinataire(s) : "
                            f"{', '.join(result['envoyes'])}"
                        )
                    else:
                        st.error(result.get("error", "Erreur envoi."))
                    if result.get("erreurs"):
                        for err in result["erreurs"]:
                            st.warning(
                                f"Échec → {err['email']} : "
                                f"{err['erreur']}"
                            )
                except Exception as e:
                    st.error(f"Erreur : {e}")

        # Programmation automatique
        st.markdown("---")
        st.subheader("Envoi automatique hebdomadaire")
        st.caption("Configure l'envoi automatique chaque semaine.")

        col1, col2 = st.columns(2)
        with col1:
            jour_envoi = st.selectbox(
                "Jour d'envoi",
                ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi"],
                key="mail_jour"
            )
        with col2:
            heure_envoi = st.selectbox(
                "Heure d'envoi",
                [f"{h:02d}:00" for h in range(6, 20)],
                index=2,
                key="mail_heure"
            )

        if st.button(
            "Activer l'envoi automatique",
            use_container_width=True,
            key="btn_auto_mail"
        ):
            try:
                from core.database import get_db, now_iso
                jours_map = {
                    "Lundi": 0, "Mardi": 1, "Mercredi": 2,
                    "Jeudi": 3, "Vendredi": 4,
                }
                with get_db() as conn:
                    conn.execute("""
                        INSERT OR REPLACE INTO parametres
                            (cle, valeur, modifie_le)
                        VALUES
                            ('mail_auto_jour',  ?, ?),
                            ('mail_auto_heure', ?, ?),
                            ('mail_auto_actif', '1', ?)
                    """, (
                        str(jours_map[jour_envoi]), now_iso(),
                        heure_envoi, now_iso(),
                        now_iso(),
                    ))
                st.success(
                    f"Envoi automatique activé : "
                    f"{jour_envoi} à {heure_envoi}"
                )
            except Exception as e:
                st.error(f"Erreur configuration : {e}")