"""Script temporaire pour générer les nuages avec les nouveaux stopwords."""
import sys, os, re, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ui.pages.nuage import STOPWORDS_FR, STOPWORDS_EN, get_texte_corpus
from wordcloud import WordCloud
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

for langue, sw, fname in [
    ("fr", STOPWORDS_FR, "nuage_fr_new.png"),
    ("en", STOPWORDS_EN, "nuage_en_new.png"),
]:
    print(f"\n--- Génération corpus {langue.upper()} ---")
    texte = get_texte_corpus(langue)
    if not texte:
        print("  Pas de texte."); continue

    texte_propre = re.sub(r"[^\w\s]", " ", texte.lower())
    texte_propre = re.sub(r"\d+",     " ", texte_propre)
    texte_propre = re.sub(r"\s+",     " ", texte_propre)

    wc = WordCloud(
        width=1200, height=600, background_color="white",
        stopwords=sw, max_words=80, colormap="Blues",
        prefer_horizontal=0.85, min_font_size=10, max_font_size=80,
        collocations=False,
    )
    wc.generate(texte_propre)

    fig, ax = plt.subplots(figsize=(14, 7))
    ax.imshow(wc, interpolation="bilinear")
    ax.axis("off")
    fig.patch.set_facecolor("white")
    plt.tight_layout(pad=0)
    plt.savefig(fname, dpi=120, bbox_inches="tight")
    plt.close()

    top10 = sorted(wc.words_.items(), key=lambda x: x[1], reverse=True)[:10]
    print(f"  Top 10 : {[w for w, _ in top10]}")
    print(f"  Sauvegardé : {fname}")
