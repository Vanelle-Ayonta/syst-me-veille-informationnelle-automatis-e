"""
ui/pages/gestion_utilisateurs.py — Gestion complète des utilisateurs
Créer, modifier, désactiver, voir les sessions actives.
"""
import streamlit as st
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
from core.database import get_db, new_id, now_iso, log_action
from core.auth import validate_password_strength
from config import ROLES, ROLE_ADMIN, ROLE_LECTEUR
import bcrypt


def render_utilisateurs(user):
    st.title("Gestion des utilisateurs")

    tab1, tab2 = st.tabs([
        "Liste des utilisateurs",
        "Créer un utilisateur",
    ])

    # ── TAB 1 : Liste ─────────────────────────────────────────────
    with tab1:
        with get_db() as conn:
            users = conn.execute("""
                SELECT id, nom, email, role,
                       actif, cree_le,
                       derniere_connexion
                FROM utilisateurs
                ORDER BY cree_le DESC
            """).fetchall()
            users = [dict(u) for u in users]

        st.caption(f"{len(users)} utilisateur(s) enregistré(s)")

        for u in users:
            is_current = u["id"] == user["id"]
            actif      = u.get("actif", 1)
            statut     = "Actif" if actif else "Désactivé"
            couleur    = "#27AE60" if actif else "#E74C3C"

            with st.expander(
                f"**{u['nom']}** — {u['email']} "
                f"· {u['role'].capitalize()}"
                f"{' (vous)' if is_current else ''}"
            ):
                col1, col2 = st.columns(2)
                with col1:
                    st.markdown(
                        f'<span style="color:{couleur};">'
                        f'● {statut}</span>',
                        unsafe_allow_html=True
                    )
                    st.caption(f"Rôle : {u['role'].capitalize()}")
                    st.caption(
                        f"Créé le : "
                        f"{(u.get('cree_le') or '')[:10]}"
                    )
                with col2:
                    st.caption(
                        f"Dernière connexion : "
                        f"{(u.get('derniere_connexion') or '—')[:10]}"
                    )

                if not is_current:
                    col_a, col_b, col_c = st.columns(3)

                    # Changer le rôle
                    with col_a:
                        nouveau_role = st.selectbox(
                            "Rôle",
                            ROLES,
                            index=ROLES.index(u["role"])
                            if u["role"] in ROLES else 0,
                            key=f"role_{u['id']}"
                        )
                        if st.button(
                            "Appliquer",
                            key=f"apply_role_{u['id']}"
                        ):
                            with get_db() as conn:
                                conn.execute("""
                                    UPDATE utilisateurs
                                    SET role = ?, modifie_le = ?
                                    WHERE id = ?
                                """, (nouveau_role, now_iso(),
                                      u["id"]))
                            log_action(
                                user["id"], "USER_ROLE_MAJ",
                                detail=(
                                    f"{u['nom']} → {nouveau_role}"
                                )
                            )
                            st.success("Rôle mis à jour.")
                            st.rerun()

                    # Activer/Désactiver
                    with col_b:
                        label = (
                            "Désactiver" if actif else "Activer"
                        )
                        if st.button(
                            label,
                            key=f"toggle_{u['id']}"
                        ):
                            with get_db() as conn:
                                conn.execute("""
                                    UPDATE utilisateurs
                                    SET actif = ?, modifie_le = ?
                                    WHERE id = ?
                                """, (0 if actif else 1,
                                      now_iso(), u["id"]))
                            log_action(
                                user["id"],
                                "USER_DESACTIVE"
                                if actif else "USER_ACTIVE",
                                detail=u["nom"]
                            )
                            st.success(
                                f"Utilisateur {label.lower()}."
                            )
                            st.rerun()

                    # Réinitialiser le mot de passe
                    with col_c:
                        if st.button(
                            "Reset MDP",
                            key=f"reset_{u['id']}"
                        ):
                            st.session_state[
                                f"reset_mdp_{u['id']}"
                            ] = True

                    if st.session_state.get(
                        f"reset_mdp_{u['id']}"
                    ):
                        with st.form(f"form_reset_{u['id']}"):
                            nouveau_mdp = st.text_input(
                                "Nouveau mot de passe",
                                type="password"
                            )
                            if st.form_submit_button(
                                "Confirmer",
                                use_container_width=True
                            ):
                                valid, msg = validate_password_strength(
                                    nouveau_mdp
                                )
                                if not valid:
                                    st.error(msg)
                                else:
                                    hash_mdp = bcrypt.hashpw(
                                        nouveau_mdp.encode("utf-8"),
                                        bcrypt.gensalt()
                                    ).decode("utf-8")
                                    with get_db() as conn:
                                        conn.execute("""
                                            UPDATE utilisateurs
                                            SET mot_de_passe = ?,
                                                modifie_le = ?
                                            WHERE id = ?
                                        """, (hash_mdp, now_iso(),
                                              u["id"]))
                                    log_action(
                                        user["id"],
                                        "USER_MDP_RESET",
                                        detail=u["nom"]
                                    )
                                    st.success("Mot de passe réinitialisé.")
                                    del st.session_state[
                                        f"reset_mdp_{u['id']}"
                                    ]
                                    st.rerun()

    # ── TAB 2 : Créer ─────────────────────────────────────────────
    with tab2:
        st.subheader("Créer un nouveau compte")

        with st.form("form_creer_user"):
            nom   = st.text_input("Nom complet *")
            email = st.text_input(
                "Adresse email *",
                placeholder="prenom.nom@beac.int"
            )
            role  = st.selectbox("Rôle *", ROLES)
            mdp   = st.text_input(
                "Mot de passe *", type="password"
            )
            mdp2  = st.text_input(
                "Confirmer *", type="password"
            )
            submitted = st.form_submit_button(
                "Créer le compte",
                use_container_width=True
            )

        if submitted:
            if not nom or not email or not mdp:
                st.error("Tous les champs sont obligatoires.")
            elif mdp != mdp2:
                st.error("Les mots de passe ne correspondent pas.")
            else:
                valid, msg = validate_password_strength(mdp)
                if not valid:
                    st.error(msg)
                else:
                    with get_db() as conn:
                        existe = conn.execute(
                            "SELECT id FROM utilisateurs "
                            "WHERE email = ?",
                            (email.lower(),)
                        ).fetchone()
                    if existe:
                        st.error("Cet email est déjà utilisé.")
                    else:
                        hash_mdp = bcrypt.hashpw(
                            mdp.encode("utf-8"),
                            bcrypt.gensalt()
                        ).decode("utf-8")
                        uid = new_id()
                        with get_db() as conn:
                            conn.execute("""
                                INSERT INTO utilisateurs
                                    (id, nom, email, mot_de_passe,
                                     role, actif, cree_le, modifie_le)
                                VALUES (?, ?, ?, ?, ?, 1, ?, ?)
                            """, (
                                uid, nom,
                                email.lower(),
                                hash_mdp, role,
                                now_iso(), now_iso()
                            ))
                        log_action(
                            user["id"], "USER_CREE",
                            detail=f"{nom} ({email})"
                        )
                        st.success(
                            f"Compte créé pour {nom}."
                        )
                        st.rerun()