"""
ui/pages/veille.py — Page Veille & filtres + Upload documents + Qualité
"""
import streamlit as st
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
from scrapers.scraper_all import orchestrer as collecter_toutes_sources
from core.database import get_db as _get_db_veille


@st.cache_data(ttl=120)
def _count_articles_veille(langue, qualite, champ_date,
                            date_debut_str, date_fin_str, mot_cle):
    """COUNT mis en cache 2 min pour éviter un hit DB à chaque interaction."""
    where_parts, params = [], []
    if langue != "Toutes":
        where_parts.append("a.langue = ?"); params.append(langue)
    if qualite != "Toutes":
        where_parts.append("a.qualite_contenu = ?"); params.append(qualite)
    if date_debut_str:
        where_parts.append(f"DATE({champ_date}) >= ?"); params.append(date_debut_str)
    if date_fin_str:
        where_parts.append(f"DATE({champ_date}) <= ?"); params.append(date_fin_str)
    if mot_cle:
        where_parts.append("(a.titre LIKE ? OR a.contenu LIKE ?)")
        params += [f"%{mot_cle}%", f"%{mot_cle}%"]
    where_sql = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""
    with _get_db_veille() as conn:
        return conn.execute(
            f"SELECT COUNT(*) FROM articles a "
            f"JOIN sources s ON a.source_id = s.id {where_sql}",
            params
        ).fetchone()[0]


def qualite_emoji(qualite):
    return {
        "complet": "🟢",
        "partiel": "🟡",
        "resume":  "🟠",
        "inconnu": "⚪",
    }.get(qualite or "", "⚪")
from core.document_processor import (
    sauvegarder_document, get_all_documents, delete_document
)
from core.database import get_db, log_action
from config import UPLOADS_DIR, DIMENSIONS_IF, CIBLES_IF, ZONES_CEMAC


def render_veille(user):
    st.title("Veille & filtres")

    tab1, tab2, tab3, tab4 = st.tabs([
        "Articles collectés",
        "Qualité du scraping",
        "Upload documents",
        "Lancer la collecte",
    ])

    # ── TAB 1 : Articles ───────────────────────────────────────────
    with tab1:
        st.subheader("Filtres")
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            dim = st.selectbox("Dimension", ["Toutes"] + DIMENSIONS_IF)
        with col2:
            cible = st.selectbox("Cible", ["Toutes"] + CIBLES_IF)
        with col3:
            zone = st.selectbox("Zone", ["Toutes"] + ZONES_CEMAC)
        with col4:
            langue = st.selectbox("Langue", ["Toutes", "fr", "en"])

        col_d0, col_d1, col_d2 = st.columns(3)
        with col_d0:
            filtre_date_sur = st.radio(
                "Filtrer les dates sur",
                ["Date de collecte", "Date de publication"],
                horizontal=True,
                key="veille_filtre_date"
            )
        with col_d1:
            date_debut = st.date_input("Du", value=None,
                                        key="veille_date_debut")
        with col_d2:
            date_fin = st.date_input("Au", value=None,
                                      key="veille_date_fin")
        qualite_filtre = st.selectbox(
            "Qualité contenu",
            ["Toutes", "complet", "partiel", "resume", "inconnu"],
            key="veille_qual"
        )

        mot_cle = st.text_input("Recherche par mot-clé", placeholder="Ex : mobile money, inclusion...")

        st.markdown("---")

        PER_PAGE = 20

        # Construire conditions WHERE
        where_parts = []
        params = []

        champ_date = (
            "a.collecte_le"
            if filtre_date_sur == "Date de collecte"
            else "a.publie_le"
        )
        if langue != "Toutes":
            where_parts.append("a.langue = ?")
            params.append(langue)
        if qualite_filtre != "Toutes":
            where_parts.append("a.qualite_contenu = ?")
            params.append(qualite_filtre)
        if date_debut:
            where_parts.append(f"DATE({champ_date}) >= ?")
            params.append(str(date_debut))
        if date_fin:
            where_parts.append(f"DATE({champ_date}) <= ?")
            params.append(str(date_fin))
        if mot_cle:
            where_parts.append("(a.titre LIKE ? OR a.contenu LIKE ?)")
            params += [f"%{mot_cle}%", f"%{mot_cle}%"]

        where_sql = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""

        # Réinitialiser la page si les filtres changent
        filtre_sig = str((langue, qualite_filtre, filtre_date_sur,
                          date_debut, date_fin, mot_cle))
        if st.session_state.get("veille_filtre_sig") != filtre_sig:
            st.session_state["veille_filtre_sig"] = filtre_sig
            st.session_state["veille_page"] = 1

        page = st.session_state.get("veille_page", 1)

        total = _count_articles_veille(
            langue, qualite_filtre, champ_date,
            str(date_debut) if date_debut else None,
            str(date_fin)   if date_fin   else None,
            mot_cle,
        )

        with get_db() as conn:
            offset = (page - 1) * PER_PAGE
            articles = [dict(r) for r in conn.execute(
                f"""SELECT a.id, a.titre, a.url_original, a.collecte_le,
                           a.publie_le, a.qualite_contenu,
                           a.contenu,
                           LENGTH(a.contenu) as taille_contenu,
                           a.langue, a.resume, s.nom as source
                    FROM articles a
                    JOIN sources s ON a.source_id = s.id
                    {where_sql}
                    ORDER BY a.collecte_le DESC
                    LIMIT ? OFFSET ?""",
                params + [PER_PAGE, offset]
            ).fetchall()]

        nb_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
        st.caption(f"{total} article(s) trouvé(s) — Page {page}/{nb_pages}")

        if total == 0:
            st.info("Aucun article ne correspond aux filtres. Lancez la collecte depuis l'onglet dédié.")
        else:
            for art in articles:
                titre  = art["titre"][:90] + "…" if len(art["titre"]) > 90 else art["titre"]
                dc = (art["collecte_le"] or "")[:10]
                dp = (art["publie_le"]   or "—")[:10]
                taille = art.get("taille_contenu", 0) or 0
                qual   = art.get("qualite_contenu", "inconnu")

                dp = (art["publie_le"] or "")[:10]
                dc = (art["collecte_le"] or "")[:10]
                date_affichee = dp if dp else dc
                label_date = f"📅 {date_affichee}" if date_affichee else ""

                with st.expander(f"**{art['source']}** · {titre}  {label_date}"):
                    col_a, col_b = st.columns(2)
                    with col_a:
                        st.caption(f"Collecté le    : {dc}")
                        st.caption(f"Publié le      : {dp}")
                    with col_b:
                        st.caption(f"Langue  : {(art.get('langue') or '').upper()}")
                        st.caption(f"Contenu : {taille:,} caractères · {qual}")

                    if art.get("resume"):
                        st.write(art["resume"])

                    col_toggle, col_lien = st.columns([1, 2])
                    with col_toggle:
                        afficher_contenu = st.toggle(
                            "Lire ici",
                            key=f"contenu_{art['id']}",
                            help="Affiche le texte stocké en base sans quitter l'application"
                        )
                    with col_lien:
                        st.markdown(
                            f"<div style='padding-top:6px'>"
                            f"<a href='{art['url_original']}' target='_blank'>"
                            f"↗ Voir la source originale</a></div>",
                            unsafe_allow_html=True
                        )

                    if afficher_contenu:
                        contenu_stocke = (art.get("contenu") or "").strip()
                        if contenu_stocke and len(contenu_stocke) >= 100:
                            st.markdown("---")
                            st.markdown(
                                f"<div style='font-size:0.92em;line-height:1.6;"
                                f"white-space:pre-wrap;'>{contenu_stocke}</div>",
                                unsafe_allow_html=True
                            )
                            if taille >= 5800:
                                st.caption(
                                    "⚠ Texte tronqué à 6 000 caractères — "
                                    "consultez la source originale pour le texte complet."
                                )
                        else:
                            st.info(
                                "Contenu textuel non disponible pour cet article "
                                "(publication PDF, page JavaScript ou résumé uniquement). "
                                "Consultez la source originale."
                            )

            # Navigation pagination
            if nb_pages > 1:
                col_prev, col_info, col_next = st.columns([1, 2, 1])
                with col_prev:
                    if page > 1 and st.button("← Précédent",
                                               use_container_width=True,
                                               key="veille_prev"):
                        st.session_state["veille_page"] = page - 1
                        st.rerun()
                with col_info:
                    st.markdown(
                        f"<div style='text-align:center;padding-top:8px;'>"
                        f"Page {page} / {nb_pages}</div>",
                        unsafe_allow_html=True
                    )
                with col_next:
                    if page < nb_pages and st.button("Suivant →",
                                                      use_container_width=True,
                                                      key="veille_next"):
                        st.session_state["veille_page"] = page + 1
                        st.rerun()

    # ── TAB 2 : Qualité du scraping ────────────────────────────────
    with tab2:
        st.subheader("Qualité du contenu collecté")

        with get_db() as conn:
            rows = conn.execute("""
                SELECT COALESCE(qualite_contenu, 'inconnu') as q,
                       COUNT(*) as nb
                FROM articles GROUP BY qualite_contenu
            """).fetchall()
        g_raw = {r["q"]: r["nb"] for r in rows}
        g = {q: g_raw.get(q, 0) for q in ("complet", "partiel", "resume", "inconnu")}
        total_arts = sum(g.values())

        if total_arts == 0:
            st.info("Aucun article en base. Lancez la collecte pour voir les statistiques.")
        else:
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("🟢 Complet", g["complet"],
                        f"{g['complet']/total_arts*100:.0f}%")
            col2.metric("🟡 Partiel",  g["partiel"],
                        f"{g['partiel']/total_arts*100:.0f}%")
            col3.metric("🟠 Résumé",   g["resume"],
                        f"{g['resume']/total_arts*100:.0f}%")
            col4.metric("⚪ Inconnu",  g["inconnu"],
                        f"{g['inconnu']/total_arts*100:.0f}%")

            st.caption(
                "**Seuils** — Complet : ≥ 2 000 caractères · "
                "Partiel : 500–1 999 · Résumé : < 500 · Inconnu : contenu vide"
            )
            st.markdown("---")

            st.subheader("Détail par source")
            with get_db() as conn:
                rows = conn.execute("""
                    SELECT s.nom, a.qualite_contenu, COUNT(*) as nb
                    FROM articles a
                    JOIN sources s ON a.source_id = s.id
                    GROUP BY s.nom, a.qualite_contenu
                """).fetchall()

            par_source: dict = {}
            for row in rows:
                nom = row["nom"]
                if nom not in par_source:
                    par_source[nom] = {"complet": 0, "partiel": 0,
                                       "resume": 0, "inconnu": 0}
                par_source[nom][row["qualite_contenu"]] = row["nb"]

            if not par_source:
                st.info("Aucune donnée par source.")
            else:
                for nom_src, counts in sorted(par_source.items()):
                    total_src = sum(counts.values())
                    if total_src == 0:
                        continue
                    pct_complet = counts["complet"] / total_src * 100

                    with st.expander(
                        f"{'⚠️' if pct_complet < 30 else '✅'} **{nom_src}** "
                        f"— {total_src} articles "
                        f"({pct_complet:.0f}% complets)"
                    ):
                        c1, c2, c3, c4 = st.columns(4)
                        c1.metric("🟢 Complet", counts["complet"])
                        c2.metric("🟡 Partiel",  counts["partiel"])
                        c3.metric("🟠 Résumé",   counts["resume"])
                        c4.metric("⚪ Inconnu",  counts["inconnu"])

                        if pct_complet < 30:
                            st.warning(
                                "Moins de 30 % d'articles complets — "
                                "vérifiez les sélecteurs CSS ou l'accès à cette source."
                            )

    # ── TAB 3 : Upload documents ───────────────────────────────────
    with tab3:
        st.subheader("Uploader un document interne")
        st.caption("Formats acceptés : PDF, DOCX, TXT — Taille max : 50 Mo")

        with st.form("form_upload"):
            fichier     = st.file_uploader(
                "Sélectionner un fichier",
                type=["pdf", "docx", "doc", "txt"]
            )
            description = st.text_area(
                "Description (optionnelle)",
                placeholder="Ex : Rapport annuel BEAC 2024, Note interne DIIF..."
            )
            submitted = st.form_submit_button("Uploader", use_container_width=True)

        if submitted:
            if not fichier:
                st.error("Veuillez sélectionner un fichier.")
            else:
                result = sauvegarder_document(
                    nom_fichier    = fichier.name,
                    contenu_bytes  = fichier.read(),
                    description    = description,
                    uploade_par    = user["id"],
                    uploads_dir    = UPLOADS_DIR,
                )
                if result["success"]:
                    log_action(user["id"], "DOCUMENT_UPLOADE",
                               "document", result["doc_id"], fichier.name)
                    st.success(result["message"])
                else:
                    st.error(result["message"])

        st.markdown("---")
        st.subheader("Documents enregistrés")
        docs = get_all_documents()

        if not docs:
            st.info("Aucun document enregistré.")
        else:
            for doc in docs:
                col1, col2 = st.columns([6, 1])
                with col1:
                    st.markdown(f"**{doc['nom_fichier']}**")
                    st.caption(
                        f"Type : {doc['type_doc'].upper()} · "
                        f"Uploadé le {doc['uploade_le'][:10]} · "
                        f"Par : {doc.get('uploade_par_nom') or '—'}"
                    )
                    if doc.get("description"):
                        st.caption(f"📝 {doc['description']}")
                with col2:
                    if st.button("Supprimer", key=f"del_doc_{doc['id']}"):
                        delete_document(doc["id"])
                        log_action(user["id"], "DOCUMENT_SUPPRIME",
                                   "document", doc["id"], doc["nom_fichier"])
                        st.rerun()

    # ── TAB 4 : Lancer la collecte (admin uniquement) ──────────────
    with tab4:
        if user["role"] != "administrateur":
            st.info("Cette fonctionnalité est réservée à l'administrateur.")
        else:
            st.subheader("Collecte manuelle")
            st.caption(
                "Lance immédiatement la collecte sur toutes les sources actives. "
                "La collecte automatique tourne en arrière-plan selon la fréquence configurée."
            )

            from core.database import get_all_sources
            sources = get_all_sources(active_only=True)
            st.metric("Sources actives", len(sources))

            if sources:
                st.markdown("**Sources qui seront interrogées :**")
                for src in sources:
                    st.markdown(
                        f"- **{src['nom']}** — `{src['type_source']}` "
                        f"· {src['langue'].upper()}"
                    )
            st.markdown("---")

            from datetime import date as _date, timedelta
            date_debut_collecte = st.date_input(
                "Collecter les articles publiés depuis le :",
                value=_date.today() - timedelta(days=30),
                max_value=_date.today(),
                key="collecte_date_debut",
            )
            st.caption(
                f"Seuls les articles publiés depuis le "
                f"**{date_debut_collecte.strftime('%d/%m/%Y')}** "
                f"seront collectés."
            )

            if st.button("Lancer la collecte maintenant", use_container_width=True):
                with st.spinner("Collecte en cours… (peut prendre plusieurs minutes)"):
                    rapport = collecter_toutes_sources(
                        date_depuis=date_debut_collecte.strftime("%Y-%m-%d")
                    )
                st.session_state["rapport_collecte"] = rapport

            # Rapport de la dernière collecte (persiste entre rerenders)
            if "rapport_collecte" in st.session_state:
                r         = st.session_state["rapport_collecte"]
                nb_nvx    = r.get("nouveaux", 0)
                nb_err    = r.get("erreurs", 0)
                duree_tot = r.get("duree_totale", 0)

                st.markdown("---")

                # Détail par source
                for nom_src, info in r.get("sources", {}).items():
                    if info["statut"] != "OK":
                        icone = "❌"
                        detail = info.get("message", "Erreur")
                    elif info["nouveaux"] > 0:
                        icone  = "✅"
                        detail = f"{info['nouveaux']} nouveau(x) article(s)"
                    else:
                        icone  = "⚪"
                        detail = "0 nouveau (déjà en base)"
                    st.markdown(f"{icone} **{nom_src}** — {detail}")

                # Message de synthèse
                synthese = (
                    f"Collecte terminée — **{nb_nvx}** nouveaux articles · "
                    f"**{nb_err}** source(s) en erreur · Durée : **{duree_tot}s**"
                )
                if nb_err == 0:
                    st.success(synthese)
                elif nb_err < 5:
                    st.warning(synthese)
                else:
                    st.error(synthese)

            from core.scheduler import scheduler_actif
            st.markdown("---")
            st.subheader("Collecte automatique")
            statut = "En cours" if scheduler_actif() else "Arrêtée"
            st.metric("Statut du planificateur", statut)

            col1, col2 = st.columns(2)
            with col1:
                if st.button("Démarrer le planificateur", use_container_width=True):
                    from core.scheduler import demarrer_scheduler
                    demarrer_scheduler()
                    log_action(user["id"], "SCHEDULER_DEMARRE")
                    st.success("Planificateur démarré.")
                    st.rerun()
            with col2:
                if st.button("Arrêter le planificateur", use_container_width=True):
                    from core.scheduler import arreter_scheduler
                    arreter_scheduler()
                    log_action(user["id"], "SCHEDULER_ARRETE")
                    st.warning("Planificateur arrêté.")
                    st.rerun()
