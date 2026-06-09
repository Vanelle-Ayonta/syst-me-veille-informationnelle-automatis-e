"""
ui/pages/nuage.py — Nuage de mots bilingue FR/EN
Deux onglets séparés, filtres par dimension et période,
stopwords spécialisés IF, clic sur mot → articles.
"""
import streamlit as st
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
from core.database import get_db
from config import DIMENSIONS_IF

# Stopwords spécialisés IF (FR + EN)
STOPWORDS_FR = {
    # Articles, pronoms, prépositions
    "le","la","les","un","une","des","de","du","et","en","au","aux",
    "ce","cet","cette","ces","il","elle","ils","elles","on","nous",
    "vous","je","tu","se","sa","son","ses","leur","leurs","que","qui",
    "quoi","dont","où","par","pour","sur","sous","dans","avec","sans",
    "plus","très","aussi","bien","tout","tous","toute","toutes","mais",
    "ou","donc","car","ni","si","même","comme","lors","selon","entre",
    "après","avant","depuis","pendant","afin","ainsi","dont",
    "est","sont","était","ont","avoir","être","faire","a","été",
    "fait","peut","doit","faut","via","notamment","cependant",
    "toutefois","néanmoins","également","plusieurs","différents",
    "certains","ceux","celle","celui","celles","autres","autre",
    "cette","elles","leur","leurs","dont","quand","alors","toujours",
    "souvent","jamais","encore","déjà","très","trop","peu","beaucoup",
    "moins","mieux","plu","pu","aller","venir","voir","savoir","tenir",
    # Termes génériques finance à filtrer
    "financial","finance","financier","financière","financiers",
    "financières","service","services","sector","secteur",
    "bank","banque","banks","banques","system","système",
    "national","international","global","mondial","régional",
    "rapport","report","page","article","lire","suite","voir",
    "plus","read","more","also","source","sources","données",
    "data","information","informations","publication","publié",
    # Noms de sites et bruits de navigation
    "digital business","business africa","digital business africa",
    "pinterest","twitter","facebook","linkedin","instagram",
    "lecture","lire la suite","en savoir plus","retour",
    "accueil","menu","recherche","contact","à propos",
    "newsletter","abonnez","inscription","connexion",
    "copyright","tous droits","réservés","politique",
    "cookies","mentions","légales","conditions",
    # Mots trop courts
    "à","l","d","n","s","m","j","c","y","qu","en","si",
    # Ajouts — bruit identifié sur corpus IF
    "ne","moi","non","pas","an","ia","pay",
    "janvier","février","mars","avril","mai","juin",
    "juillet","août","septembre","octobre","novembre","décembre",
    "point","jour","cours","soit","nouveau","nouvelle",
    "publications","trimestre","hausse","baisse",
    "montant","moyen","contre",
    # Artefacts observés sur les nuages générés
    "e","deux","ans","fin","pro","min","dce","plu","pu","jet",
}

STOPWORDS_EN = {
    # Common words
    "the","a","an","and","or","but","in","on","at","to","for",
    "of","with","by","from","as","is","are","was","were","be",
    "been","being","have","has","had","do","does","did","will",
    "would","could","should","may","might","shall","can","need",
    "this","that","these","those","it","its","they","their",
    "we","our","you","your","he","she","him","her","his","hers",
    "not","no","nor","so","yet","both","either","neither","each",
    "more","most","other","some","such","than","then","too","very",
    "just","also","well","even","still","back","any","only","into",
    "through","during","before","after","above","below","between",
    "out","up","down","off","over","under","again","further",
    "while","where","when","which","who","whom","what","why","how",
    # Generic finance terms
    "financial","finance","sector","service","services","bank",
    "banks","banking","system","national","international","global",
    "report","reports","new","year","including","based","provide",
    "support","country","countries","development","developed",
    "page","article","read","more","also","source","data",
    "information","publication","published","according","said",
    "one","two","three","first","second","third","last","next",
    # Navigation noise
    "pinterest","twitter","facebook","linkedin","instagram",
    "home","menu","search","contact","about","newsletter",
    "subscribe","login","copyright","rights","reserved",
    "policy","cookies","terms","conditions","privacy",
    # Short words
    "mr","dr","st","vs","et","al","ie","eg","re",
    # Single letters (UI artefacts)
    "e","t","g","s","i","b","c",
    # Ajouts — bruit identifié sur corpus IF
    "afi","cgap","blog","photo","around",
    "them","all","use","help","way","many",
    "get","got","make","made","said","says",
    "must","want","view","see",
    "click","here","site","com","www","http","pdf","download",
    "date","month","day","time","ago","now","recent",
    # Artefacts observés sur les nuages générés
    "gsma","minutes","there","making","often","find","across","men",
}


# Traductions des dimensions IF en anglais pour le corpus EN
DIMENSIONS_EN = {
    "Accès": [
        "access", "financial access", "account", "unbanked",
        "bancarisation", "agent banking", "branchless"
    ],
    "Utilisation": [
        "usage", "utilization", "transaction", "payment",
        "mobile money", "transfer", "remittance"
    ],
    "Qualité": [
        "quality", "reliability", "affordability",
        "transparency", "efficiency"
    ],
    "Éducation financière": [
        "financial literacy", "financial education",
        "financial awareness", "financial capability"
    ],
    "Protection des consommateurs": [
        "consumer protection", "fraud", "cybersecurity",
        "data privacy", "complaint", "dispute"
    ],
    "Innovation financière": [
        "fintech", "innovation", "digital finance", "cbdc",
        "blockchain", "regtech", "insurtech", "open banking"
    ],
}


@st.cache_data(ttl=3600)
def get_texte_corpus(langue: str, dimension: str = None,
                     mois_debut: str = None,
                     mois_fin: str = None) -> str:
    with get_db() as conn:
        query  = """
            SELECT a.titre, a.contenu
            FROM articles a
            WHERE a.langue = ?
              AND a.contenu IS NOT NULL
              AND LENGTH(a.contenu) > 100
        """
        params = [langue]

        if mois_debut:
            query  += " AND SUBSTR(a.collecte_le,1,7) >= ?"
            params.append(mois_debut)
        if mois_fin:
            query  += " AND SUBSTR(a.collecte_le,1,7) <= ?"
            params.append(mois_fin)

        rows = conn.execute(query, params).fetchall()

    if not rows:
        return ""

    textes = []
    for row in rows:
        titre   = row["titre"]   or ""
        contenu = row["contenu"] or ""
        texte_combine = (titre + " " + contenu).lower()

        if dimension:
            if langue == "fr":
                mots_cles = [dimension.lower()]
            else:
                mots_cles = DIMENSIONS_EN.get(dimension, [
                    dimension.lower()
                ])

            pertinent = any(
                mot in texte_combine for mot in mots_cles
            )
            if not pertinent:
                continue

        textes.append(titre + " " + contenu[:2000])

    return " ".join(textes)


def generer_nuage(texte: str, langue: str,
                  max_words: int = 80):
    """Génère et affiche le nuage de mots."""
    if not texte or len(texte) < 100:
        st.info("Pas assez de données pour générer le nuage.")
        return None

    try:
        from wordcloud import WordCloud
        import matplotlib.pyplot as plt
        import re

        # Nettoyage basique
        texte_propre = re.sub(r'[^\w\s]', ' ', texte.lower())
        texte_propre = re.sub(r'\d+', ' ', texte_propre)
        texte_propre = re.sub(r'\s+', ' ', texte_propre)

        stopwords = STOPWORDS_FR if langue == "fr" else STOPWORDS_EN

        wc = WordCloud(
            width=900,
            height=450,
            background_color="white",
            stopwords=stopwords,
            max_words=max_words,
            colormap="Blues",
            prefer_horizontal=0.85,
            min_font_size=10,
            max_font_size=80,
            collocations=False,
        )
        wc.generate(texte_propre)

        fig, ax = plt.subplots(figsize=(12, 6))
        ax.imshow(wc, interpolation="bilinear")
        ax.axis("off")
        fig.patch.set_facecolor("white")
        plt.tight_layout(pad=0)
        st.pyplot(fig)
        plt.close()

        return wc.words_

    except ImportError:
        st.error("Bibliothèque wordcloud non installée. "
                 "Exécutez : pip install wordcloud matplotlib")
        return None
    except Exception as e:
        st.error(f"Erreur génération nuage : {e}")
        return None


@st.cache_data(ttl=300)
def articles_par_mot(mot: str, langue: str) -> list:
    """Retourne les articles contenant un mot donné."""
    with get_db() as conn:
        rows = conn.execute("""
            SELECT a.titre, a.url_original,
                   a.collecte_le, s.nom as source
            FROM articles a
            JOIN sources s ON a.source_id = s.id
            WHERE a.langue = ?
              AND (LOWER(a.titre)   LIKE ?
                OR LOWER(a.contenu) LIKE ?)
            ORDER BY a.collecte_le DESC
            LIMIT 20
        """, (langue, f"%{mot.lower()}%",
               f"%{mot.lower()}%")).fetchall()
    return [dict(r) for r in rows]


def render_nuage(user):
    st.title("Nuage de mots")
    st.caption(
        "Visualisation des thématiques dominantes "
        "dans les articles collectés."
    )

    # Filtres globaux
    col1, col2, col3, col4, col5 = st.columns([2, 1, 1, 1, 1])
    with col1:
        dimension = st.selectbox(
            "Dimension IF",
            ["Toutes"] + DIMENSIONS_IF,
            key="nuage_dim"
        )
    with col2:
        annee_debut = st.selectbox(
            "Année début",
            ["Toutes"] + [str(a) for a in range(2020, 2027)],
            key="nuage_annee_d"
        )
    with col3:
        mois_debut_sel = st.selectbox(
            "Mois début",
            ["Tous"] + [f"{m:02d}" for m in range(1, 13)],
            key="nuage_mois_d"
        )
    with col4:
        annee_fin = st.selectbox(
            "Année fin",
            ["Toutes"] + [str(a) for a in range(2020, 2027)],
            index=len([str(a) for a in range(2020, 2027)]),
            key="nuage_annee_f"
        )
    with col5:
        mois_fin_sel = st.selectbox(
            "Mois fin",
            ["Tous"] + [f"{m:02d}" for m in range(1, 13)],
            key="nuage_mois_f"
        )

    dim_filtre = None if dimension == "Toutes" else dimension
    mois_d = (
        f"{annee_debut}-{mois_debut_sel}"
        if annee_debut != "Toutes" and mois_debut_sel != "Tous"
        else (annee_debut + "-01" if annee_debut != "Toutes" else None)
    )
    mois_f = (
        f"{annee_fin}-{mois_fin_sel}"
        if annee_fin != "Toutes" and mois_fin_sel != "Tous"
        else (annee_fin + "-12" if annee_fin != "Toutes" else None)
    )

    st.markdown("---")

    # Deux onglets FR / EN
    tab_fr, tab_en = st.tabs([
        "Corpus francophone",
        "Corpus anglophone",
    ])

    with tab_fr:
        st.subheader("Sources francophones")

        with get_db() as conn:
            nb_fr = conn.execute(
                "SELECT COUNT(*) FROM articles WHERE langue = 'fr'"
            ).fetchone()[0]
        st.caption(f"{nb_fr} articles en français dans la base")

        if st.button("Générer le nuage FR",
                     key="btn_nuage_fr",
                     use_container_width=True):
            with st.spinner("Génération en cours..."):
                texte = get_texte_corpus(
                    "fr", dim_filtre, mois_d, mois_f
                )
                if texte:
                    mots = generer_nuage(texte, "fr")
                    if mots:
                        st.session_state["mots_fr"] = mots
                else:
                    st.info(
                        "Aucun article francophone trouvé "
                        "avec ces filtres."
                    )

        # Clic sur un mot → articles
        if "mots_fr" in st.session_state:
            st.markdown("**Cliquez sur un mot pour voir les articles :**")
            mots_tries = sorted(
                st.session_state["mots_fr"].items(),
                key=lambda x: x[1], reverse=True
            )[:30]
            cols = st.columns(5)
            for i, (mot, _) in enumerate(mots_tries):
                with cols[i % 5]:
                    if st.button(mot, key=f"mot_fr_{mot}"):
                        st.session_state["mot_selectionne_fr"] = mot

            if "mot_selectionne_fr" in st.session_state:
                mot = st.session_state["mot_selectionne_fr"]
                arts = articles_par_mot(mot, "fr")
                st.markdown(
                    f"**Articles contenant « {mot} »"
                    f" ({len(arts)}) :**"
                )
                for art in arts:
                    st.markdown(
                        f"- **{art['source']}** — "
                        f"{(art['titre'] or '')[:70]}  "
                        f"[Lire]({art['url_original']})"
                    )

    with tab_en:
        st.subheader("Sources anglophones")

        with get_db() as conn:
            nb_en = conn.execute(
                "SELECT COUNT(*) FROM articles WHERE langue = 'en'"
            ).fetchone()[0]
        st.caption(f"{nb_en} articles en anglais dans la base")

        if st.button("Générer le nuage EN",
                     key="btn_nuage_en",
                     use_container_width=True):
            with st.spinner("Génération en cours..."):
                texte = get_texte_corpus(
                    "en", dim_filtre, mois_d, mois_f
                )
                if texte:
                    mots = generer_nuage(texte, "en")
                    if mots:
                        st.session_state["mots_en"] = mots
                else:
                    st.info(
                        "Aucun article anglophone trouvé "
                        "avec ces filtres."
                    )

        if "mots_en" in st.session_state:
            st.markdown("**Cliquez sur un mot pour voir les articles :**")
            mots_tries = sorted(
                st.session_state["mots_en"].items(),
                key=lambda x: x[1], reverse=True
            )[:30]
            cols = st.columns(5)
            for i, (mot, _) in enumerate(mots_tries):
                with cols[i % 5]:
                    if st.button(mot, key=f"mot_en_{mot}"):
                        st.session_state["mot_selectionne_en"] = mot

            if "mot_selectionne_en" in st.session_state:
                mot = st.session_state["mot_selectionne_en"]
                arts = articles_par_mot(mot, "en")
                st.markdown(
                    f"**Articles contenant « {mot} »"
                    f" ({len(arts)}) :**"
                )
                for art in arts:
                    st.markdown(
                        f"- **{art['source']}** — "
                        f"{(art['titre'] or '')[:70]}  "
                        f"[Lire]({art['url_original']})"
                    )
