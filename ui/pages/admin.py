"""
ui/pages/admin.py — Tableau de bord d'administration
Vue globale du système, santé RAG, paramètres.
"""
import streamlit as st
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
from core.database import get_db, now_iso, log_action
from config import SCRAPING_INTERVAL_HOURS


def render_admin(user):
    st.title("Administration")

    if user["role"] != "administrateur":
        st.error("Accès réservé à l'administrateur.")
        return

    tab1, tab2, tab3, tab4 = st.tabs([
        "Santé du système",
        "Pipeline RAG",
        "Paramètres",
        "Migration base",
    ])

    # ── TAB 1 : Santé du système ──────────────────────────────────
    with tab1:
        st.subheader("État général")

        col1, col2, col3, col4 = st.columns(4)

        with get_db() as conn:
            nb_users = conn.execute(
                "SELECT COUNT(*) FROM utilisateurs"
            ).fetchone()[0]
            nb_sources = conn.execute(
                "SELECT COUNT(*) FROM sources WHERE active=1"
            ).fetchone()[0]
            nb_articles = conn.execute(
                "SELECT COUNT(*) FROM articles"
            ).fetchone()[0]
            nb_chunks = conn.execute(
                "SELECT COUNT(*) FROM chunks"
            ).fetchone()[0]
            derniere_collecte = conn.execute(
                "SELECT MAX(collecte_le) FROM articles"
            ).fetchone()[0]
            nb_logs = conn.execute(
                "SELECT COUNT(*) FROM logs_activite"
            ).fetchone()[0]

        col1.metric("Utilisateurs", nb_users)
        col2.metric("Sources actives", nb_sources)
        col3.metric("Articles", nb_articles)
        col4.metric("Chunks RAG", nb_chunks)

        st.markdown("---")
        col5, col6 = st.columns(2)
        col5.metric(
            "Dernière collecte",
            (derniere_collecte or "—")[:10]
        )
        col6.metric("Entrées logs", nb_logs)

        # Vérification index FAISS
        st.markdown("---")
        st.subheader("Index FAISS")
        try:
            from core.rag.indexer import get_stats_index
            si = get_stats_index()
            c1, c2, c3 = st.columns(3)
            c1.metric(
                "Vecteurs indexés",
                si.get("total_vecteurs", 0)
            )
            c2.metric(
                "Taille index",
                f"{si.get('taille_mo', 0)} Mo"
            )
            c3.metric(
                "En mémoire",
                "Oui" if si.get("en_memoire") else "Non"
            )
        except Exception as e:
            st.warning(f"Index FAISS : {e}")

    # ── TAB 2 : Pipeline RAG ──────────────────────────────────────
    with tab2:
        st.subheader("Gestion du pipeline RAG")

        try:
            from core.rag.chunker import get_stats_chunks
            from core.rag.indexer import get_stats_index
            sc = get_stats_chunks()
            si = get_stats_index()

            col1, col2 = st.columns(2)
            with col1:
                st.markdown("**Chunking**")
                st.metric(
                    "Articles chunkés",
                    sc.get("articles_chunkés", 0)
                )
                st.metric(
                    "Articles restants",
                    sc.get("articles_restants", 0)
                )
                st.metric("Chunks total", sc.get("total", 0))
                hp = sc.get("hors_perimetre", 0)
                if hp:
                    st.metric(
                        "Hors périmètre (filtrés)",
                        hp,
                        help="Articles sans mot-clé IF/finance — "
                             "présents en DB mais non indexés."
                    )

            with col2:
                st.markdown("**Indexation FAISS**")
                st.metric(
                    "Chunks indexés",
                    sc.get("indexes", 0)
                )
                st.metric(
                    "En attente",
                    sc.get("en_attente", 0)
                )
                st.metric(
                    "Vecteurs FAISS",
                    si.get("total_vecteurs", 0)
                )

        except Exception as e:
            st.warning(f"Stats RAG : {e}")

        st.markdown("---")

        col_a, col_b, col_c = st.columns(3)

        with col_a:
            if st.button(
                "Lancer pipeline incrémental",
                use_container_width=True
            ):
                with st.spinner("Pipeline en cours..."):
                    try:
                        from core.rag.pipeline import run_pipeline
                        stats = run_pipeline()
                        st.success(
                            f"{stats.get('chunks',0)} chunks · "
                            f"{stats.get('indexés',0)} indexés"
                        )
                        log_action(
                            user["id"], "RAG_PIPELINE_LANCE"
                        )
                    except Exception as e:
                        st.error(f"Erreur : {e}")

        with col_b:
            if st.button(
                "Reconstruire l'index",
                use_container_width=True
            ):
                with st.spinner(
                    "Reconstruction complète..."
                ):
                    try:
                        from core.rag.indexer import (
                            reconstruire_index_complet
                        )
                        stats = reconstruire_index_complet()
                        st.success(
                            f"{stats.get('total_index',0)} "
                            f"vecteurs reconstruits"
                        )
                        log_action(
                            user["id"], "RAG_INDEX_RECONSTRUIT"
                        )
                    except Exception as e:
                        st.error(f"Erreur : {e}")

        with col_c:
            if st.button(
                "Décharger de la RAM",
                use_container_width=True
            ):
                try:
                    from core.rag.indexer import decharger_index
                    decharger_index()
                    st.success("Index déchargé.")
                except Exception as e:
                    st.error(f"Erreur : {e}")

    # ── TAB 3 : Paramètres ────────────────────────────────────────
    with tab3:
        st.subheader("Paramètres du système")

        with get_db() as conn:
            params = {
                r["cle"]: r["valeur"]
                for r in conn.execute(
                    "SELECT cle, valeur FROM parametres"
                ).fetchall()
            }

        st.markdown("**Collecte automatique**")
        with st.form("form_params"):
            freq = st.number_input(
                "Fréquence de collecte (heures)",
                min_value=1,
                max_value=720,
                value=int(
                    params.get(
                        "scraping_interval",
                        str(SCRAPING_INTERVAL_HOURS)
                    )
                ),
                key="param_freq"
            )
            st.markdown("**Email automatique**")
            mail_actif = st.checkbox(
                "Envoi hebdomadaire actif",
                value=params.get("mail_auto_actif") == "1",
                key="param_mail_actif"
            )
            jours_options = [
                "Lundi", "Mardi", "Mercredi",
                "Jeudi", "Vendredi"
            ]
            mail_jour = st.selectbox(
                "Jour d'envoi",
                jours_options,
                index=int(params.get("mail_auto_jour", 0)),
                key="param_mail_jour"
            )
            mail_heure = st.selectbox(
                "Heure d'envoi",
                [f"{h:02d}:00" for h in range(6, 20)],
                index=int(
                    params.get("mail_auto_heure", "08:00")
                    .split(":")[0]
                ) - 6,
                key="param_mail_heure"
            )

            if st.form_submit_button(
                "Enregistrer",
                use_container_width=True
            ):
                jours_map = {
                    "Lundi": 0, "Mardi": 1, "Mercredi": 2,
                    "Jeudi": 3, "Vendredi": 4,
                }
                with get_db() as conn:
                    for cle, val in [
                        ("scraping_interval", str(freq)),
                        ("mail_auto_actif",
                         "1" if mail_actif else "0"),
                        ("mail_auto_jour",
                         str(jours_map[mail_jour])),
                        ("mail_auto_heure", mail_heure),
                    ]:
                        conn.execute("""
                            INSERT OR REPLACE INTO parametres
                                (cle, valeur, modifie_le)
                            VALUES (?, ?, ?)
                        """, (cle, val, now_iso()))
                log_action(
                    user["id"], "PARAMETRES_MAJ"
                )
                st.success("Paramètres enregistrés.")
                st.rerun()

    # ── TAB 4 : Migration base de données ────────────────────────────────────
    with tab4:
        st.subheader("Importer une base de données locale")
        st.info(
            "Uploadez votre fichier `veille_diif.db` local pour remplacer "
            "la base vide du serveur. Toutes les données existantes sur le "
            "serveur seront **écrasées**. À faire une seule fois."
        )

        from config import DB_PATH
        col_a, col_b = st.columns(2)
        with col_a:
            with get_db() as conn:
                nb_art = conn.execute(
                    "SELECT COUNT(*) FROM articles"
                ).fetchone()[0]
                nb_src = conn.execute(
                    "SELECT COUNT(*) FROM sources"
                ).fetchone()[0]
            st.metric("Articles en base (serveur)", nb_art)
            st.metric("Sources en base (serveur)", nb_src)

        uploaded_db = st.file_uploader(
            "Sélectionner le fichier .db local",
            type=["db"],
            key="upload_db_migration"
        )

        if uploaded_db is not None:
            st.warning(
                f"⚠️ Ceci va remplacer la base à `{DB_PATH}` "
                f"({nb_art} articles actuels). Confirmer ?"
            )
            if st.button("✅ Confirmer le remplacement", type="primary"):
                import shutil
                backup_path = DB_PATH + ".bak"
                try:
                    # Sauvegarde préventive
                    if os.path.exists(DB_PATH):
                        shutil.copy2(DB_PATH, backup_path)
                    # Écriture du nouveau fichier
                    with open(DB_PATH, "wb") as f:
                        f.write(uploaded_db.read())
                    log_action(user["id"], "DB_MIGRATION_IMPORT")
                    st.success(
                        f"Base importée avec succès ! "
                        f"(ancien fichier sauvegardé en .bak)"
                    )
                    st.rerun()
                except Exception as e:
                    st.error(f"Erreur lors de l'import : {e}")

        st.divider()
        st.subheader("Exporter la base serveur")
        if st.button("📥 Télécharger la base actuelle"):
            if os.path.exists(DB_PATH):
                with open(DB_PATH, "rb") as f:
                    st.download_button(
                        label="Cliquer pour télécharger veille_diif.db",
                        data=f.read(),
                        file_name="veille_diif.db",
                        mime="application/octet-stream"
                    )
            else:
                st.error("Fichier base introuvable.")