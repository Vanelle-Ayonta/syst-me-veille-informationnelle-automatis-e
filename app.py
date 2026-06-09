import streamlit as st
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core.auth import get_current_user, logout
from ui.components.header import render_header


def inject_css():
    st.markdown("""
    <style>

    /* ── Sidebar — toujours visible ── */
    [data-testid="stSidebar"],
    section[data-testid="stSidebar"] {
        display: flex !important;
        visibility: visible !important;
        transform: none !important;
        margin-left: 0 !important;
        left: 0 !important;
        background: linear-gradient(180deg, #001d3d 0%, #002B5C 100%) !important;
        border-right: 2px solid #C8A951 !important;
        min-width: 240px !important;
        width: 21rem !important;
    }
    [data-testid="stSidebar"] * {
        color: #ffffff !important;
    }
    [data-testid="collapsedControl"] {
        display: flex !important;
        visibility: visible !important;
        opacity: 1 !important;
        background: #C8A951 !important;
        border-radius: 0 8px 8px 0 !important;
        width: 24px !important;
    }
    [data-testid="collapsedControl"] svg {
        fill: #002B5C !important;
    }

    /* ── Boutons sidebar ── */
    [data-testid="stSidebar"] .stButton > button {
        width: 100%;
        background: transparent !important;
        color: #ffffff !important;
        border: none !important;
        border-left: 3px solid transparent !important;
        border-radius: 0 !important;
        text-align: left !important;
        padding: 10px 16px !important;
        font-size: 13px !important;
        font-weight: 500 !important;
        letter-spacing: 0.03em !important;
        transition: all 0.2s ease !important;
        margin-bottom: 2px !important;
        box-shadow: none !important;
    }
    [data-testid="stSidebar"] .stButton > button:hover {
        background: rgba(200,169,81,0.15) !important;
        border-left: 3px solid #C8A951 !important;
        color: #C8A951 !important;
        transform: translateX(4px) !important;
    }

    /* ── Fond général ── */
    .stApp {
        background-color: #F4F6F9 !important;
    }

    /* ── Onglets st.tabs ── */
    .stTabs [data-baseweb="tab-list"] {
        background: #ffffff !important;
        border-radius: 8px 8px 0 0 !important;
        border-bottom: 2px solid #C8A951 !important;
        gap: 4px !important;
        padding: 4px 4px 0 !important;
    }
    .stTabs [data-baseweb="tab"] {
        background: #f0f2f6 !important;
        border-radius: 6px 6px 0 0 !important;
        color: #002B5C !important;
        font-weight: 600 !important;
        font-size: 13px !important;
        padding: 8px 20px !important;
        border: 1px solid #ddd !important;
        border-bottom: none !important;
        transition: all 0.2s ease !important;
    }
    .stTabs [data-baseweb="tab"]:hover {
        background: #C8A951 !important;
        color: #ffffff !important;
        border-color: #C8A951 !important;
    }
    .stTabs [aria-selected="true"] {
        background: #002B5C !important;
        color: #ffffff !important;
        border-color: #002B5C !important;
    }
    .stTabs [data-baseweb="tab-panel"] {
        background: #ffffff !important;
        border-radius: 0 0 8px 8px !important;
        border: 1px solid #ddd !important;
        border-top: none !important;
        padding: 16px !important;
    }

    /* ── Boutons principaux ── */
    .stButton > button {
        background: #002B5C !important;
        color: #ffffff !important;
        border: none !important;
        border-radius: 6px !important;
        font-weight: 600 !important;
        font-size: 13px !important;
        padding: 8px 20px !important;
        transition: all 0.2s ease !important;
        box-shadow: 0 2px 6px rgba(0,43,92,0.2) !important;
    }
    .stButton > button:hover {
        background: #C8A951 !important;
        color: #002B5C !important;
        box-shadow: 0 4px 12px rgba(200,169,81,0.3) !important;
        transform: translateY(-1px) !important;
    }

    /* ── Download buttons ── */
    .stDownloadButton > button {
        background: #27AE60 !important;
        color: #ffffff !important;
        border: none !important;
        border-radius: 6px !important;
        font-weight: 600 !important;
    }
    .stDownloadButton > button:hover {
        background: #219A52 !important;
        transform: translateY(-1px) !important;
    }

    /* ── Inputs ── */
    .stTextInput > div > div > input,
    .stTextArea > div > div > textarea {
        border-radius: 6px !important;
        border: 1.5px solid #ddd !important;
        background: #ffffff !important;
        color: #333 !important;
        transition: border-color 0.2s ease !important;
    }
    .stTextInput > div > div > input:focus,
    .stTextArea > div > div > textarea:focus {
        border-color: #002B5C !important;
        box-shadow: 0 0 0 2px rgba(0,43,92,0.1) !important;
    }

    /* ── Expanders ── */
    .streamlit-expanderHeader {
        background: #ffffff !important;
        border-radius: 8px !important;
        border-left: 4px solid #002B5C !important;
        font-weight: 600 !important;
        color: #002B5C !important;
        padding: 12px 16px !important;
        margin-bottom: 4px !important;
        box-shadow: 0 1px 4px rgba(0,0,0,0.06) !important;
    }
    .streamlit-expanderHeader:hover {
        border-left-color: #C8A951 !important;
    }
    .streamlit-expanderContent {
        background: #fafafa !important;
        border-radius: 0 0 8px 8px !important;
        border: 1px solid #eee !important;
        border-top: none !important;
        padding: 12px 16px !important;
    }

    /* ── Chatbot bulles ── */
    [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) {
        background: linear-gradient(135deg,#002B5C,#003d7a) !important;
        border-radius: 16px 16px 4px 16px !important;
        padding: 12px 16px !important;
        margin-left: 15% !important;
        box-shadow: 0 2px 8px rgba(0,43,92,0.2) !important;
    }
    [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) * {
        color: #ffffff !important;
    }
    [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-assistant"]) {
        background: #FDF8EC !important;
        border-radius: 16px 16px 16px 4px !important;
        padding: 12px 16px !important;
        margin-right: 15% !important;
        border-left: 3px solid #C8A951 !important;
        box-shadow: 0 2px 8px rgba(200,169,81,0.1) !important;
    }
    [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-assistant"]) * {
        color: #002B5C !important;
    }
    [data-testid="stChatInput"] {
        border: 2px solid #002B5C !important;
        border-radius: 12px !important;
        background: #ffffff !important;
    }
    [data-testid="stChatInput"]:focus-within {
        border-color: #C8A951 !important;
        box-shadow: 0 0 0 3px rgba(200,169,81,0.15) !important;
    }

    /* ── Titres ── */
    h1 {
        color: #002B5C !important;
        font-weight: 700 !important;
        border-bottom: 2px solid #C8A951 !important;
        padding-bottom: 8px !important;
        margin-bottom: 16px !important;
    }
    h2 { color: #002B5C !important; font-weight: 600 !important; }
    h3 { color: #003d7a !important; }

    /* ── Masquer éléments Streamlit natifs ── */
    #MainMenu { visibility: hidden !important; }
    footer { visibility: hidden !important; }
    header { visibility: hidden !important; }
    [data-testid="stToolbar"] { display: none !important; }

    /* ── Footer personnalisé ── */
    .footer-diif {
        position: fixed;
        bottom: 0;
        left: 0;
        right: 0;
        background: #001d3d;
        border-top: 1px solid #C8A951;
        padding: 6px 24px;
        text-align: center;
        font-size: 10px;
        color: rgba(255,255,255,0.5);
        z-index: 999;
        letter-spacing: 0.04em;
    }

    </style>

    <div class="footer-diif">
        DIIF / BEAC &mdash; Système de veille informationnelle automatisée
        &nbsp;|&nbsp; © 2026 &nbsp;|&nbsp; Confidentiel
    </div>
    """, unsafe_allow_html=True)


st.set_page_config(
    page_title="Veille DIIF/BEAC",
    page_icon="assets/logo_beac.png",
    layout="wide",
    initial_sidebar_state="expanded",
)
inject_css()

# Force la sidebar ouverte à chaque chargement
import streamlit.components.v1 as _components
_components.html(
    "<script>"
    "(function(){"
    "function fx(){"
    "try{"
    "var w=window.parent;"
    "var sb=w.document.querySelector('section[data-testid=\"stSidebar\"]');"
    "if(!sb){setTimeout(fx,150);return;}"
    "var r=sb.getBoundingClientRect();"
    "if(r.x<0||r.width<80){"
    "var btn=w.document.querySelector('[data-testid=\"collapsedControl\"]');"
    "if(btn)btn.click();"
    "}"
    "}catch(e){}"
    "}"
    "setTimeout(fx,400);"
    "})();"
    "</script>",
    height=0,
    scrolling=False,
)

st.markdown("""
<style>
#MainMenu, footer { display:none !important; }

/* Sidebar */
[data-testid="stSidebar"] {
    background: linear-gradient(180deg,#002B5C 0%,#001830 100%);
    border-right: 1px solid rgba(200,169,81,0.25);
}
[data-testid="stSidebar"] * { color:#fff !important; }
[data-testid="stSidebar"] .stButton > button {
    background: transparent !important;
    border: 0.5px solid rgba(200,169,81,0.2) !important;
    color: #fff !important;
    width: 100% !important;
    text-align: left !important;
    padding: 0.52rem 1rem !important;
    border-radius: 6px !important;
    margin-bottom: 2px !important;
    font-size: 13px !important;
    font-weight: 400 !important;
    letter-spacing: 0.01em !important;
    transition: all 0.18s ease !important;
}
[data-testid="stSidebar"] .stButton > button:hover {
    background: rgba(200,169,81,0.14) !important;
    border-color: #C8A951 !important;
    color: #C8A951 !important;
    transform: translateX(5px) !important;
    padding-left: 1.2rem !important;
}
[data-testid="stSidebar"] .stButton > button:active {
    transform: translateX(2px) !important;
}

/* Contenu */
.main .block-container {
    padding-top: 4.5rem !important;
    padding-left: 2.5rem !important;
    padding-right: 2.5rem !important;
    max-width: 1200px;
}

/* Typographie */
h1 {
    color: #002B5C !important;
    font-size: 26px !important;
    font-weight: 700 !important;
    border-bottom: 2px solid #C8A951;
    padding-bottom: 0.5rem;
    margin-bottom: 1.5rem !important;
}
h2 { color: #002B5C !important; font-size: 18px !important; }
h3 { color: #003d80 !important; }

/* Métriques */
[data-testid="metric-container"] {
    background: #fff !important;
    border: 1px solid rgba(0,43,92,0.1) !important;
    border-left: 3px solid #C8A951 !important;
    border-radius: 10px !important;
    padding: 1rem 1.2rem !important;
    transition: box-shadow 0.2s, transform 0.2s !important;
}
[data-testid="metric-container"]:hover {
    box-shadow: 0 4px 16px rgba(0,43,92,0.1) !important;
    transform: translateY(-1px) !important;
}
[data-testid="metric-container"] label {
    color: #666 !important;
    font-size: 12px !important;
    text-transform: uppercase !important;
    letter-spacing: 0.05em !important;
}
[data-testid="metric-container"] [data-testid="stMetricValue"] {
    color: #002B5C !important;
    font-size: 28px !important;
    font-weight: 700 !important;
}

/* Boutons globaux */
.stButton > button {
    border: 1px solid rgba(0,43,92,0.25) !important;
    border-radius: 7px !important;
    font-size: 13px !important;
    transition: all 0.18s !important;
}
.stButton > button:hover {
    border-color: #C8A951 !important;
    color: #002B5C !important;
    background: rgba(200,169,81,0.07) !important;
}

/* Expanders */
[data-testid="stExpander"] {
    border: 1px solid rgba(0,43,92,0.12) !important;
    border-radius: 10px !important;
    margin-bottom: 6px !important;
}
[data-testid="stExpander"]:hover {
    border-color: rgba(200,169,81,0.4) !important;
}

/* Séparateurs */
hr { border-color: rgba(0,43,92,0.1) !important; }
</style>
""", unsafe_allow_html=True)

if "auth_token" not in st.session_state:
    st.session_state["auth_token"] = None
if "page" not in st.session_state:
    st.session_state["page"] = "login"

user = get_current_user(st.session_state)

if not user:
    from ui.pages.login import render_login
    render_login()
    st.stop()

render_header()

# Sidebar
with st.sidebar:
    st.markdown(
        '<hr style="border-color:rgba(200,169,81,0.2);margin:0.8rem 0 0.8rem;">',
        unsafe_allow_html=True
    )

    # Info utilisateur
    st.markdown(
        f'<div style="padding:0.5rem 0.75rem;'
        f'background:rgba(200,169,81,0.1);'
        f'border-radius:8px;border-left:3px solid #C8A951;margin-bottom:10px;">'
        f'<div style="font-size:13px;font-weight:600;color:#fff;">{user["nom"]}</div>'
        f'<div style="font-size:11px;color:rgba(255,255,255,0.45);margin-top:1px;">'
        f'{user["role"].capitalize()}</div></div>',
        unsafe_allow_html=True
    )
    st.markdown(
        '<hr style="border-color:rgba(200,169,81,0.2);margin:0.2rem 0 0.6rem;">',
        unsafe_allow_html=True
    )

    page_courante = st.session_state.get("page", "dashboard")
    from core.database import count_non_lues
    nb_notifs = count_non_lues(user["id"])

    def nav_btn(label, key):
        is_active = page_courante == key
        suffix = "  ●" if key == "dashboard" and nb_notifs > 0 else ""
        if is_active:
            st.markdown(
                f'<div style="'
                f'background:#C8A951;color:#ffffff;'
                f'font-weight:500;font-size:13px;'
                f'padding:10px 16px;border-radius:0;'
                f'border:none;border-left:3px solid transparent;'
                f'margin-bottom:2px;letter-spacing:0.03em;'
                f'text-align:center;width:100%;box-sizing:border-box;">'
                f'{label}{suffix}'
                f'</div>',
                unsafe_allow_html=True
            )
        else:
            clicked = st.button(f"{label}{suffix}", key=f"nav_{key}",
                                use_container_width=True)
            if clicked:
                st.session_state["page"] = key
                st.rerun()

    pages = [
        ("Tableau de bord",  "dashboard"),
        ("Veille & filtres", "veille"),
        ("Nuage de mots",    "nuage"),
        ("Suggestions",      "suggestions"),
        ("Chatbot",          "chatbot"),
        ("Exporter",         "export"),
    ]
    for label, key in pages:
        nav_btn(label, key)

    if user["role"] == "administrateur":
        st.markdown(
            '<hr style="border-color:rgba(200,169,81,0.2);margin:0.8rem 0 0.4rem;">',
            unsafe_allow_html=True
        )
        st.markdown(
            '<div style="font-size:9.5px;color:rgba(200,169,81,0.55);'
            'text-transform:uppercase;letter-spacing:0.1em;'
            'padding:0 0.5rem 0.4rem;">Administration</div>',
            unsafe_allow_html=True
        )
        admin = [
            ("Gestion sources",       "sources"),
            ("Utilisateurs",          "utilisateurs"),
            ("Logs d\'activité",      "logs"),
            ("Administration système","admin"),
        ]
        for label, key in admin:
            nav_btn(label, key)

    st.markdown(
        '<hr style="border-color:rgba(200,169,81,0.2);margin:0.8rem 0 0.4rem;">',
        unsafe_allow_html=True
    )
    if st.button("Déconnexion", use_container_width=True):
        logout(st.session_state)
        st.session_state["page"] = "login"
        st.rerun()

# Routage
page = st.session_state.get("page", "dashboard")
if page == "dashboard":
    from ui.pages.dashboard import render_dashboard; render_dashboard(user)
elif page == "veille":
    from ui.pages.veille import render_veille; render_veille(user)
elif page == "nuage":
    from ui.pages.nuage import render_nuage; render_nuage(user)
elif page == "suggestions":
    from ui.pages.suggestions_page import render_suggestions; render_suggestions(user)
elif page == "chatbot":
    from ui.pages.chatbot import render_chatbot; render_chatbot(user)
elif page == "export":
    from ui.pages.export import render_export; render_export(user)
elif page == "sources" and user["role"] == "administrateur":
    from ui.pages.gestion_sources import render_sources; render_sources(user)
elif page == "utilisateurs" and user["role"] == "administrateur":
    from ui.pages.gestion_utilisateurs import render_utilisateurs; render_utilisateurs(user)
elif page == "logs" and user["role"] == "administrateur":
    from ui.pages.logs import render_logs; render_logs(user)
elif page == "admin" and user["role"] == "administrateur":
    from ui.pages.admin import render_admin; render_admin(user)
else:
    from ui.pages.dashboard import render_dashboard; render_dashboard(user)
