"""
ui/components/header.py — Bande supérieure fixe BEAC
Logo + titre centrés ensemble, date/heure à droite.
"""
import streamlit as st


def render_header(user=None):
    from datetime import datetime
    import base64, os

    now = datetime.now().strftime("%d/%m/%Y  %H:%M")
    logo_path = "assets/logo_beac.png"

    if os.path.exists(logo_path):
        with open(logo_path, "rb") as f:
            logo_b64 = base64.b64encode(f.read()).decode()
        logo_html = (
            f'<img src="data:image/png;base64,{logo_b64}" '
            f'style="height:64px;width:auto;margin-right:16px;flex-shrink:0;" />'
        )
    else:
        logo_html = (
            '<span style="font-size:24px;font-weight:800;'
            'color:#C8A951;letter-spacing:3px;margin-right:16px;">BEAC</span>'
        )

    st.markdown(
        "<div style='"
        "position:fixed;top:0;left:0;right:0;z-index:1000;"
        "background:linear-gradient(90deg,#001020 0%,#002B5C 50%,#001836 100%);"
        "border-bottom:4px solid #C8A951;"
        "height:80px;"
        "display:flex;align-items:center;"
        "padding:0 32px;"
        "box-shadow:0 4px 20px rgba(0,0,0,0.4);"
        "'>"
        # Zone centrale : logo + texte côte à côte
        "<div style='flex:1;display:flex;align-items:center;justify-content:center;'>"
        + logo_html +
        "<div style='text-align:left;'>"
        "<div style='"
        "font-size:22px;font-weight:800;color:#ffffff;"
        "letter-spacing:0.08em;text-transform:uppercase;"
        "text-shadow:0 2px 8px rgba(0,0,0,0.3);"
        "'>Système de Veille Informationnelle</div>"
        "<div style='"
        "font-size:11px;color:#C8A951;"
        "letter-spacing:0.08em;margin-top:4px;"
        "font-weight:500;text-transform:uppercase;"
        "'>Département de l'Inclusion et de l'Innovation Financières — BEAC"
        "</div>"
        "</div>"
        "</div>"
        # Zone droite : date
        "<div style='flex:0 0 auto;text-align:right;'>"
        "<div style='font-size:15px;color:#ffffff;font-weight:600;'>"
        + now +
        "</div>"
        "<div style='font-size:11px;color:#C8A951;margin-top:3px;"
        "letter-spacing:0.08em;'>DIIF / BEAC — CEMAC"
        "</div>"
        "</div>"
        "</div>"
        "<div style='height:80px;'></div>",
        unsafe_allow_html=True
    )