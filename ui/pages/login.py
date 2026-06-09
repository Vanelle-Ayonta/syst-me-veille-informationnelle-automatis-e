import streamlit as st
import sys, os, base64
sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
from core.auth import (login, generate_reset_token,
                       reset_password, validate_password_strength)
from datetime import datetime

def render_login():
    now = datetime.now()

    logo_path = os.path.join(
        os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))),
        "assets", "logo_beac.png"
    )
    if os.path.exists(logo_path):
        with open(logo_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        logo_topbar = f'<img src="data:image/png;base64,{b64}" style="height:52px;width:auto;display:block;" />'
        logo_card   = f'<img src="data:image/png;base64,{b64}" style="height:70px;width:auto;display:block;margin:0 auto 1rem;" />'
    else:
        logo_topbar = '<span style="color:#C8A951;font-weight:700;font-size:15px;">BEAC</span>'
        logo_card   = '<div style="color:#002B5C;font-size:36px;font-weight:700;text-align:center;margin-bottom:1rem;">BEAC</div>'

    st.markdown(f"""
    <style>
    #MainMenu, footer, header[data-testid="stHeader"],
    [data-testid="stToolbar"], .stDeployButton {{ display:none !important; }}

    @keyframes fadeIn {{
        from {{ opacity:0; transform:translateY(24px); }}
        to   {{ opacity:1; transform:translateY(0); }}
    }}
    @keyframes float {{
        0%,100% {{ transform:translateY(0px); }}
        50%      {{ transform:translateY(-10px); }}
    }}
    @keyframes borderglow {{
        0%,100% {{ border-top-color: rgba(200,169,81,0.5); }}
        50%      {{ border-top-color: rgba(200,169,81,1.0); }}
    }}

    [data-testid="stAppViewContainer"] {{
        background: linear-gradient(140deg, #001228 0%, #002B5C 55%, #003f80 100%) !important;
        min-height: 100vh;
    }}
    [data-testid="stAppViewContainer"] > .main {{
        background: transparent !important;
        padding-top: 0 !important;
    }}
    [data-testid="stSidebar"] {{ display: none !important; }}

    /* Bande supérieure — logo+titre centrés ensemble */
    .login-topbar {{
        position: fixed; top:0; left:0; right:0; z-index:9999;
        background: #002B5C;
        height: 104px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 0 3rem;
        border-bottom: 3px solid #C8A951;
        box-shadow: 0 3px 20px rgba(0,0,0,0.45);
    }}
    .login-topbar-center {{
        position: absolute;
        left: 50%;
        transform: translateX(-50%);
        display: flex;
        align-items: center;
        gap: 16px;
    }}
    .login-topbar-text {{
        display: flex;
        flex-direction: column;
    }}
    .login-topbar-title {{
        color: #fff;
        font-size: 22px;
        font-weight: 700;
        letter-spacing: 0.02em;
        line-height: 1.2;
    }}
    .login-topbar-sub {{
        color: #C8A951;
        font-size: 12px;
        letter-spacing: 0.04em;
        margin-top: 4px;
    }}
    .login-topbar-right {{
        color: rgba(255,255,255,0.7);
        font-size: 12px;
        text-align: right;
        line-height: 1.8;
        margin-left: auto;
        z-index: 1;
    }}
    .login-topbar-date {{ color:#C8A951; font-size:14px; font-weight:600; }}

    /* Particules */
    .pt {{
        position: fixed; border-radius: 50%;
        pointer-events: none; z-index: 1;
        animation: float linear infinite;
    }}

    /* Centrage vertical de la carte */
    .main .block-container {{
        padding-top: 104px !important;
        padding-bottom: 0 !important;
        min-height: calc(100vh - 104px);
        display: flex;
        align-items: center;
        justify-content: center;
    }}

    /* Carte unique fusionnée */
    .login-card {{
        background: rgba(255,255,255,0.97);
        border-radius: 18px;
        padding: 2.5rem 2.8rem 2.2rem;
        width: 100%;
        max-width: 440px;
        margin: 0 auto;
        border-top: 4px solid #C8A951;
        animation: fadeIn .65s ease both, borderglow 4s ease-in-out infinite;
        box-shadow: 0 24px 64px rgba(0,0,0,0.5);
    }}
    .login-card-title {{
        text-align: center; color: #002B5C;
        font-size: 19px; font-weight: 700;
        margin-bottom: 4px;
    }}
    .login-card-sub {{
        text-align: center; color: #666;
        font-size: 12px; line-height: 1.6;
        margin-bottom: 1.5rem;
    }}
    .login-sep {{
        border: none;
        border-top: 1px solid rgba(0,43,92,0.1);
        margin: 0 0 1.4rem;
    }}

    /* Labels */
    .stTextInput > label {{
        color: #002B5C !important;
        font-size: 13px !important;
        font-weight: 500 !important;
    }}
    /* Champs */
    .stTextInput input {{
        border: 1.5px solid rgba(0,43,92,0.18) !important;
        border-radius: 8px !important;
        font-size: 14px !important;
        background: #fafbfd !important;
        transition: border-color .2s, box-shadow .2s !important;
    }}
    .stTextInput input:focus {{
        border-color: #C8A951 !important;
        box-shadow: 0 0 0 3px rgba(200,169,81,0.15) !important;
        background: #fff !important;
    }}

    /* Bouton Se connecter */
    div[data-testid="stFormSubmitButton"] > button {{
        background: #002B5C !important;
        color: #fff !important;
        border: none !important;
        border-radius: 9px !important;
        font-weight: 600 !important;
        font-size: 15px !important;
        width: 100% !important;
        margin-top: 0.5rem !important;
        letter-spacing: 0.03em !important;
        transition: all .22s ease !important;
    }}
    div[data-testid="stFormSubmitButton"] > button:hover {{
        background: #C8A951 !important;
        color: #002B5C !important;
        transform: translateY(-2px) !important;
        box-shadow: 0 8px 24px rgba(200,169,81,0.45) !important;
    }}

    /* Bouton secondaire */
    .stButton > button {{
        background: transparent !important;
        color: rgba(255,255,255,0.6) !important;
        border: 1px solid rgba(255,255,255,0.18) !important;
        border-radius: 8px !important;
        font-size: 13px !important;
        margin-top: 0.5rem !important;
        transition: all .2s !important;
    }}
    .stButton > button:hover {{
        color: #C8A951 !important;
        border-color: #C8A951 !important;
        background: rgba(200,169,81,0.07) !important;
    }}
    </style>

    <!-- Bande supérieure — logo + titre centrés ensemble -->
    <div class="login-topbar">
        <div class="login-topbar-center">
            {logo_topbar}
            <div class="login-topbar-text">
                <div class="login-topbar-title">Système de Veille Financière</div>
                <div class="login-topbar-sub">
                    Département de l'Inclusion et de l'Innovation Financières — BEAC
                </div>
            </div>
        </div>
        <div class="login-topbar-right">
            <div class="login-topbar-date">{now.strftime("%d/%m/%Y")} &nbsp; {now.strftime("%H:%M")}</div>
            <div>DIIF / BEAC — CEMAC</div>
        </div>
    </div>

    <!-- Particules flottantes -->
    <div class="pt" style="width:6px;height:6px;background:rgba(200,169,81,0.4);top:22%;left:6%;animation-duration:7s;animation-delay:0s;"></div>
    <div class="pt" style="width:4px;height:4px;background:rgba(255,255,255,0.18);top:68%;left:89%;animation-duration:9s;animation-delay:1s;"></div>
    <div class="pt" style="width:8px;height:8px;background:rgba(200,169,81,0.2);top:82%;left:14%;animation-duration:6s;animation-delay:2s;"></div>
    <div class="pt" style="width:5px;height:5px;background:rgba(255,255,255,0.12);top:38%;left:82%;animation-duration:8s;animation-delay:0.5s;"></div>
    <div class="pt" style="width:7px;height:7px;background:rgba(200,169,81,0.22);top:55%;left:4%;animation-duration:10s;animation-delay:3s;"></div>
    <div class="pt" style="width:4px;height:4px;background:rgba(255,255,255,0.14);top:14%;left:94%;animation-duration:7s;animation-delay:4s;"></div>
    """, unsafe_allow_html=True)

    # Detect reset token in URL (email link)
    _token_url = st.query_params.get("reset_token")
    if _token_url and st.session_state.get("login_mode", "login") == "login":
        st.session_state["login_mode"] = "reset_confirm"
        st.session_state["reset_token_prefill"] = _token_url

    mode = st.session_state.get("login_mode", "login")
    col1, col2, col3 = st.columns([1, 1.8, 1])
    with col2:
        st.markdown(f"""
        <div class="login-card">
            {logo_card}
            <div class="login-card-title">Système de Veille DIIF-BEAC</div>
            <div class="login-card-sub">
                Accès réservé au personnel autorisé<br>
                Département de l'Inclusion et de l'Innovation Financières
            </div>
            <hr class="login-sep">
        </div>
        """, unsafe_allow_html=True)

        if mode == "login":
            _form_login()
        elif mode == "reset_request":
            _form_reset_request()
        elif mode == "reset_confirm":
            _form_reset_confirm()


def _form_login():
    with st.form("form_login"):
        email     = st.text_input("Adresse email", placeholder="votre@beac.int")
        password  = st.text_input("Mot de passe", type="password")
        submitted = st.form_submit_button("Se connecter", use_container_width=True)
    if submitted:
        if not email or not password:
            st.error("Veuillez renseigner l'email et le mot de passe.")
            return
        result = login(email.strip().lower(), password)
        if result["success"]:
            st.session_state["auth_token"] = result["token"]
            st.session_state["page"]       = "dashboard"
            st.rerun()
        else:
            st.error(result["error"])
    if st.button("Mot de passe oublié ?", use_container_width=True):
        st.session_state["login_mode"] = "reset_request"
        st.rerun()


def _form_reset_request():
    st.markdown("#### Réinitialisation du mot de passe")
    st.caption(
        "Entrez votre adresse email. "
        "Un lien de réinitialisation (valable 1 heure) vous sera envoyé."
    )
    with st.form("form_reset_req"):
        email     = st.text_input("Adresse email")
        submitted = st.form_submit_button("Envoyer le lien", use_container_width=True)
    if submitted and email:
        result = generate_reset_token(email.strip().lower())
        if result.get("success"):
            st.success(result.get("message", "Email envoyé."))
        else:
            st.error(result.get("error", "Erreur inconnue."))
    if st.button("Retour", use_container_width=True):
        st.session_state["login_mode"] = "login"
        st.rerun()


def _form_reset_confirm():
    st.markdown("#### Nouveau mot de passe")
    prefill = st.session_state.get("reset_token_prefill", "")
    with st.form("form_reset_confirm"):
        token    = st.text_input(
            "Token de réinitialisation",
            value=prefill,
            disabled=bool(prefill),
        )
        new_pwd  = st.text_input("Nouveau mot de passe", type="password")
        new_pwd2 = st.text_input("Confirmer le mot de passe", type="password")
        submitted = st.form_submit_button("Réinitialiser", use_container_width=True)
    if submitted:
        tok = (prefill or token).strip()
        if new_pwd != new_pwd2:
            st.error("Les mots de passe ne correspondent pas.")
            return
        valid, msg = validate_password_strength(new_pwd)
        if not valid:
            st.error(msg)
            return
        result = reset_password(tok, new_pwd)
        if result["success"]:
            st.success(result.get("message", "Mot de passe réinitialisé. Connectez-vous."))
            st.session_state["login_mode"] = "login"
            st.session_state.pop("reset_token_prefill", None)
            st.query_params.clear()
            st.rerun()
        else:
            st.error(result["error"])
    if st.button("Retour", use_container_width=True):
        st.session_state["login_mode"] = "login"
        st.session_state.pop("reset_token_prefill", None)
        st.rerun()
