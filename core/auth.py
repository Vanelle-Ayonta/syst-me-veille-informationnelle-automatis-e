import os
import sys
import uuid
import bcrypt
import jwt
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import SECRET_KEY, JWT_ALGORITHM, JWT_EXPIRY_HOURS
from core.database import (
    get_utilisateur_by_email, get_utilisateur_by_id,
    update_derniere_connexion, set_reset_token,
    get_utilisateur_by_reset_token, clear_reset_token,
    update_utilisateur, log_action, get_db, now_iso,
)

def hash_password(password):
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def verify_password(password, hashed):
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except Exception:
        return False

def create_token(user_id, role):
    payload = {
        "sub":  user_id,
        "role": role,
        "iat":  datetime.utcnow(),
        "exp":  datetime.utcnow() + timedelta(hours=JWT_EXPIRY_HOURS),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=JWT_ALGORITHM)

def decode_token(token):
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except Exception:
        return None

def login(email, password):
    user = get_utilisateur_by_email(email)
    if not user:
        return {"success": False, "token": None, "user": None,
                "error": "Email introuvable."}
    if not user.get("actif"):
        return {"success": False, "token": None, "user": None,
                "error": "Compte désactivé. Contactez l'administrateur."}
    if not verify_password(password, user["mot_de_passe"]):
        log_action(user["id"], "LOGIN_ECHEC", detail="Mot de passe incorrect")
        return {"success": False, "token": None, "user": None,
                "error": "Mot de passe incorrect."}
    token = create_token(user["id"], user["role"])
    update_derniere_connexion(user["id"])
    log_action(user["id"], "LOGIN_OK")
    safe_user = {k: v for k, v in user.items() if k != "mot_de_passe"}
    return {"success": True, "token": token, "user": safe_user, "error": None}

def get_current_user(session_state):
    token = session_state.get("auth_token")
    if not token:
        return None
    payload = decode_token(token)
    if not payload:
        session_state.pop("auth_token", None)
        return None
    user = get_utilisateur_by_id(payload["sub"])
    if not user or not user.get("actif"):
        return None
    return {k: v for k, v in user.items() if k != "mot_de_passe"}

def is_admin(session_state):
    user = get_current_user(session_state)
    return user is not None and user.get("role") == "administrateur"

def require_auth(session_state):
    import streamlit as st
    user = get_current_user(session_state)
    if not user:
        st.warning("Vous devez être connecté pour accéder à cette page.")
        st.stop()
    return user

def require_admin(session_state):
    import streamlit as st
    user = require_auth(session_state)
    if user.get("role") != "administrateur":
        st.error("Accès réservé à l'administrateur.")
        st.stop()
    return user

def logout(session_state):
    user_id = None
    if "auth_token" in session_state:
        payload = decode_token(session_state["auth_token"])
        if payload:
            user_id = payload.get("sub")
        session_state.pop("auth_token", None)
    if user_id:
        log_action(user_id, "LOGOUT")

def send_reset_email(email: str, token: str) -> bool:
    """
    Envoie un email de réinitialisation de mot de passe.
    Retourne True si envoi réussi, False sinon.
    """
    from config import (SMTP_HOST, SMTP_PORT,
                        SMTP_USER, SMTP_PASSWORD, APP_URL)

    lien = f"{APP_URL}?reset_token={token}"

    sujet = "Réinitialisation de votre mot de passe — Veille DIIF/BEAC"
    corps_html = f"""
    <html><body style="font-family:Arial,sans-serif;color:#333;">
    <div style="max-width:500px;margin:0 auto;padding:2rem;">
        <div style="background:#002B5C;padding:1rem 2rem;
                    border-bottom:3px solid #C8A951;">
            <h2 style="color:#fff;margin:0;">Système de Veille DIIF/BEAC</h2>
        </div>
        <div style="padding:2rem;background:#f9f9f9;
                    border:1px solid #eee;">
            <p>Bonjour,</p>
            <p>Une demande de réinitialisation de mot de passe
               a été effectuée pour votre compte.</p>
            <p>Cliquez sur le bouton ci-dessous pour définir
               un nouveau mot de passe :</p>
            <div style="text-align:center;margin:2rem 0;">
                <a href="{lien}"
                   style="background:#002B5C;color:#fff;
                          padding:0.75rem 2rem;
                          border-radius:6px;
                          text-decoration:none;
                          font-weight:600;">
                    Réinitialiser mon mot de passe
                </a>
            </div>
            <p style="color:#888;font-size:12px;">
                Ce lien est valable <strong>1 heure</strong>.<br>
                Si vous n'avez pas fait cette demande,
                ignorez cet email — votre mot de passe
                ne sera pas modifié.
            </p>
            <p style="color:#888;font-size:11px;">
                Lien direct : {lien}
            </p>
        </div>
        <div style="padding:1rem;text-align:center;
                    color:#aaa;font-size:11px;">
            DIIF / BEAC — Système de veille automatisée
        </div>
    </div>
    </body></html>
    """

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = sujet
        msg["From"]    = f"Veille DIIF/BEAC <{SMTP_USER}>"
        msg["To"]      = email
        msg.attach(MIMEText(corps_html, "html", "utf-8"))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as srv:
            srv.ehlo()
            srv.starttls()
            srv.login(SMTP_USER, SMTP_PASSWORD)
            srv.sendmail(SMTP_USER, email, msg.as_string())
        return True
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(
            f"[EMAIL] Erreur envoi : {e}"
        )
        return False


def generate_reset_token(email: str) -> dict:
    """
    Génère un token de réinitialisation et l'envoie par email.
    Limite : 3 demandes par heure par email.
    """
    with get_db() as conn:
        user = conn.execute(
            "SELECT id, email, nom FROM utilisateurs WHERE email = ?",
            (email.lower(),)
        ).fetchone()

        if not user:
            return {
                "success": True,
                "message": (
                    "Si cet email est enregistré, "
                    "vous recevrez un lien de réinitialisation."
                )
            }

        une_heure_ago = (
            datetime.utcnow().replace(microsecond=0)
            - timedelta(hours=1)
        ).isoformat()
        tentatives = conn.execute("""
            SELECT COUNT(*) FROM reset_tokens
            WHERE email = ?
              AND cree_le > ?
        """, (email.lower(), une_heure_ago)).fetchone()[0]

        if tentatives >= 3:
            return {
                "success": False,
                "error": (
                    "Trop de demandes. "
                    "Veuillez réessayer dans 1 heure."
                )
            }

        token = str(uuid.uuid4())
        expire_le = (
            datetime.utcnow() + timedelta(hours=1)
        ).isoformat()

        conn.execute("""
            INSERT INTO reset_tokens
                (id, email, token, expire_le,
                 utilise, cree_le)
            VALUES (?, ?, ?, ?, 0, ?)
        """, (
            str(uuid.uuid4()), email.lower(),
            token, expire_le, now_iso()
        ))

    envoye = send_reset_email(email, token)

    if envoye:
        return {
            "success": True,
            "message": (
                "Un email de réinitialisation a été envoyé "
                "à votre adresse. Vérifiez votre boîte mail "
                "(et vos spams)."
            )
        }
    else:
        return {
            "success": False,
            "error": (
                "Erreur lors de l'envoi de l'email. "
                "Contactez l'administrateur."
            )
        }


def reset_password(token: str, nouveau_mdp: str) -> dict:
    """
    Réinitialise le mot de passe via token email.
    Vérifie : token valide, non expiré, non utilisé,
    nouveau mot de passe différent de l'ancien.
    """
    with get_db() as conn:
        row = conn.execute("""
            SELECT rt.email, rt.expire_le, rt.utilise
            FROM reset_tokens rt
            WHERE rt.token = ?
        """, (token,)).fetchone()

        if not row:
            return {
                "success": False,
                "error": "Token invalide ou expiré."
            }

        if row["utilise"]:
            return {
                "success": False,
                "error": "Ce lien a déjà été utilisé."
            }

        if datetime.fromisoformat(row["expire_le"]) < datetime.utcnow():
            return {
                "success": False,
                "error": "Ce lien a expiré. Faites une nouvelle demande."
            }

        email = row["email"]

        user = conn.execute(
            "SELECT id, mot_de_passe FROM utilisateurs WHERE email = ?",
            (email,)
        ).fetchone()

        if not user:
            return {
                "success": False,
                "error": "Utilisateur introuvable."
            }

        if bcrypt.checkpw(
            nouveau_mdp.encode("utf-8"),
            user["mot_de_passe"].encode("utf-8")
        ):
            return {
                "success": False,
                "error": (
                    "Le nouveau mot de passe doit être "
                    "différent de l'ancien."
                )
            }

        hash_mdp = bcrypt.hashpw(
            nouveau_mdp.encode("utf-8"),
            bcrypt.gensalt()
        ).decode("utf-8")

        conn.execute("""
            UPDATE utilisateurs
            SET mot_de_passe = ?, modifie_le = ?
            WHERE id = ?
        """, (hash_mdp, now_iso(), user["id"]))

        conn.execute("""
            UPDATE reset_tokens
            SET utilise = 1
            WHERE token = ?
        """, (token,))

    return {
        "success": True,
        "message": "Mot de passe réinitialisé avec succès."
    }

def validate_password_strength(password):
    if len(password) < 8:
        return False, "Au moins 8 caractères requis."
    if not any(c.isupper() for c in password):
        return False, "Au moins une lettre majuscule requise."
    if not any(c.isdigit() for c in password):
        return False, "Au moins un chiffre requis."
    return True, "Mot de passe valide."
