"""
scrapers/cleaner.py — Nettoyage du texte pour le pipeline RAG
Copie de cleaner.py adaptée pour fonctionner dans le dossier scrapers/
"""
import re
import html
import unicodedata
import logging

LONGUEUR_MINIMALE = 100

log = logging.getLogger(__name__)

PATTERNS_COMMUNS = [
    r'\b(Facebook|Twitter|LinkedIn|Instagram|WhatsApp|YouTube|TikTok|Telegram)\b',
    r'\b(Tweet|Like|Share|Partager|Retweeter|Suivre|Follow)\b',
    r'(Follow us|Suivez-nous|Suivez nous)',
    r'\b(Home|Accueil|Back to top|Retour en haut|Haut de page)\b',
    r'(Previous|Next|Précédent|Suivant|Page \d+ of \d+)',
    r'(Read more|Lire la suite|Lire plus|En savoir plus|See more)',
    r'(Related articles?|Articles? (liés?|connexes?|similaires?))',
    r'(Tags?|Catégorie|Category|Filed under)',
    r'(All rights reserved|Tous droits réservés|©\s*\d{4})',
    r'(Copyright [\w\s]+\d{4})',
    r'(Terms (of use|and conditions)|Conditions (d\'utilisation|générales?))',
    r'(Privacy [Pp]olicy|Politique de confidentialité)',
    r'(Cookie[s]?( policy| notice)?|Politique des? cookies?)',
    r'(Subscribe|Abonnez?-vous|S\'abonner|Newsletter|Sign up|Inscrivez?-vous)',
    r'(Email alert|Alerte mail|Recevoir nos? alertes?)',
    r'\b(PDF|DOC|DOCX|XLS|XLSX|PPT|CSV|ZIP)\b(?!\s*\w)',
    r'(Download|Télécharger|Téléchargement|Download PDF)',
    r'(Print|Imprimer|Impression)',
    r'(Copy link|Copier le lien)',
    r'(Advertisement|Publicité|Sponsored|Sponsorisé)',
]

PATTERNS_FR = [
    r'(Lire aussi\s*:?)',
    r'(À (lire aussi|voir aussi|découvrir)\s*:?)',
    r'(Voir aussi\s*:?)',
    r'(Source\s*:\s*(AFP|Reuters|APA|Xinhua)\b)',
    r'(Mis à jour le|Modifié le|Publié le|Rédigé par|Par )',
    r'(Retour à l\'accueil|Retour au sommaire)',
    r'(Nos autres articles|Dans la même rubrique)',
    r'(Rejoindre la conversation|Laisser un commentaire|Commentaires?)',
    r'(Partager (cet article|cette page|sur))',
    r'(Temps de lecture\s*:\s*\d+\s*(min|minutes?))',
    r'(Article (suivant|précédent))',
    r'(Dernière mise à jour|Dernière modification)',
    r'(Vous aimerez aussi|À ne pas manquer)',
    r'(La rédaction|Notre équipe|L\'équipe)',
]

PATTERNS_EN = [
    r'(Read also\s*:?|Also read\s*:?)',
    r'(See also\s*:?|Related\s*:?)',
    r'(Source\s*:\s*(AFP|Reuters|AP|Xinhua)\b)',
    r'(Updated (on|at)|Published (on|at)|Written by|By )',
    r'(Back to home|Back to top)',
    r'(More articles|In the same category)',
    r'(Join the conversation|Leave a comment|Comments?)',
    r'(Share this (article|page|post|story))',
    r'(Reading time\s*:\s*\d+\s*min)',
    r'(Next article|Previous article)',
    r'(Last updated|Last modified)',
    r'(You may also like|Don\'t miss)',
    r'(Our team|The editorial team)',
    r'(Disclaimer|Disclosure)',
    r'(Click here to|Learn more about)',
]

RE_COMMUNS = [re.compile(p, re.IGNORECASE) for p in PATTERNS_COMMUNS]
RE_FR      = [re.compile(p, re.IGNORECASE) for p in PATTERNS_FR]
RE_EN      = [re.compile(p, re.IGNORECASE) for p in PATTERNS_EN]


def normaliser_unicode(texte: str) -> str:
    if not texte: return ""
    texte = unicodedata.normalize("NFKC", texte)
    texte = "".join(
        c for c in texte
        if unicodedata.category(c) not in ("Cc","Cf") or c in ("\n","\t")
    )
    return texte

def decoder_html(texte: str) -> str:
    if not texte: return ""
    texte = html.unescape(texte)
    texte = texte.replace(" "," ").replace("​","")
    return texte

def supprimer_bruit(texte: str, langue: str) -> str:
    if not texte: return ""
    lignes = texte.split("\n")
    lignes_propres = []
    patterns_actifs = RE_COMMUNS + (RE_FR if langue == "fr" else RE_EN)
    for ligne in lignes:
        ls = ligne.strip()
        est_bruit = False
        for p in patterns_actifs:
            if p.fullmatch(ls):
                est_bruit = True; break
            if len(ls) < 60 and p.search(ls):
                est_bruit = True; break
        if not est_bruit:
            for p in patterns_actifs:
                ligne = p.sub(" ", ligne)
            lignes_propres.append(ligne)
    return "\n".join(lignes_propres)

def supprimer_titre_duplique(contenu: str, titre: str) -> str:
    if not contenu or not titre: return contenu
    titre_norm = titre.strip().lower()
    lignes = contenu.split("\n")
    nouvelles = list(lignes)
    for i, ligne in enumerate(lignes[:5]):
        if ligne.strip().lower() == titre_norm:
            nouvelles[i] = ""; break
        if titre_norm[:40] in ligne.strip().lower():
            nouvelles[i] = ""; break
    return "\n".join(nouvelles)

def nettoyer_espaces(texte: str) -> str:
    if not texte: return ""
    texte = re.sub(r'[ \t]+',' ', texte)
    lignes = [l.strip() for l in texte.split("\n")]
    lignes = [l for l in lignes if len(l) >= 3 or l == ""]
    resultat = []
    prec_vide = False
    for ligne in lignes:
        if ligne == "":
            if not prec_vide: resultat.append(ligne)
            prec_vide = True
        else:
            resultat.append(ligne)
            prec_vide = False
    return "\n".join(resultat).strip()

def nettoyer(texte: str, titre: str = "", langue: str = "fr"):
    if not texte: return None
    texte = normaliser_unicode(texte)
    texte = decoder_html(texte)
    texte = supprimer_bruit(texte, langue)
    if titre:
        texte = supprimer_titre_duplique(texte, titre)
    texte = nettoyer_espaces(texte)
    if len(texte) < LONGUEUR_MINIMALE:
        return None
    return texte
