"""
core/classification.py — Classification par mots-clés (sans LLM).

Pur, instantané, sans dépendance réseau/IA : utilisable par les scrapers
(insertion), les scripts de backfill, la page Veille et l'agent.
Classe un texte selon :
  - les 6 dimensions d'inclusion financière (DIMENSIONS_IF) ;
  - la zone géographique (ZONES_CEMAC) ;
  - la cible prioritaire (CIBLES_IF).
"""
from __future__ import annotations

import unicodedata


KEYWORDS_DIMENSIONS: dict[str, list[str]] = {
    "Accès": [
        "compte", "bancarisation", "acces", "accès", "agence", "guichet",
        "point de service", "point de vente", "proximite", "proximité",
        "infrastructure", "couverture", "reseau", "réseau", "succursale",
        "institution financiere", "institution financière",
        "interoperabilite", "interopérabilité", "ouverture de compte",
        "desservir", "non bancarise", "non bancarisé",
    ],
    "Utilisation": [
        "transaction", "paiement", "mobile money", "transfert",
        "credit", "crédit", "epargne", "épargne", "depot", "dépôt",
        "retrait", "mobile banking", "monnaie electronique",
        "monnaie électronique", "utilisation", "usage", "frequence",
        "fréquence", "actif", "portefeuille", "virement",
        "prelevement", "prélèvement",
    ],
    "Qualité": [
        "qualite", "qualité", "fiabilite", "fiabilité", "service",
        "satisfaction", "confiance", "securite", "sécurité",
        "cout", "coût", "tarif", "frais", "transparence", "performance",
        "accessibilite", "accessibilité", "delai", "délai",
        "experience utilisateur", "expérience utilisateur", "ergonomie",
    ],
    "Éducation financière": [
        "education", "éducation", "formation", "litteratie", "littératie",
        "sensibilisation", "alphabetisation", "alphabétisation",
        "competence", "compétence", "connaissance", "apprentissage",
        "programme", "campagne", "atelier", "seminaire", "séminaire",
        "pedagogie", "pédagogie", "culture financiere",
        "culture financière", "education financiere",
        "éducation financière",
    ],
    "Protection des consommateurs": [
        "protection", "consommateur", "reclamation", "réclamation",
        "plainte", "fraude", "arnaque", "reglementation", "réglementation",
        "supervision", "controle", "contrôle", "conformite", "conformité",
        "droit", "litige", "remboursement", "garantie", "ombudsman",
        "mediation", "médiation", "tribunal", "juridique",
        "protection du consommateur",
    ],
    "Innovation financière": [
        "innovation", "fintech", "technologie", "numerique", "numérique",
        "digital", "blockchain", "intelligence artificielle", "ia", "ai",
        "api", "open banking", "crypto", "cbdc", "monnaie numerique",
        "monnaie numérique", "startup", "disruption", "plateforme",
        "agregateur", "agrégateur", "suptech", "regtech",
        "innovation financiere", "innovation financière",
    ],
}

# Zone : pays CEMAC (les plus spécifiques d'abord), puis zone large.
_ZONE_ALIASES: dict[str, list[str]] = {
    "Cameroun":             ["cameroun", "cameroon"],
    "Guinée Équatoriale":   ["guinee equatoriale", "equatorial guinea"],
    "Gabon":                ["gabon"],
    "Congo":                ["congo", "brazzaville"],
    "RCA":                  ["centrafric", "central african", "rca"],
    "Tchad":                ["tchad", "chad"],
}

# Cible prioritaire (CIBLES_IF) → mots-clés de détection.
_CIBLE_KEYWORDS: dict[str, list[str]] = {
    "Femmes +25 ans":     ["femme", "femmes", "women", "woman", "feminin",
                            "féminin", "genre", "gender"],
    "Jeunes 15-24 ans":   ["jeune", "jeunes", "youth", "young", "adolescent"],
    "Populations rurales": ["rural", "rurale", "rurales", "campagne",
                            "agricole", "agriculture", "village"],
    "MPME":               ["mpme", "pme", "tpe", "sme", "msme",
                            "entrepreneur", "microentreprise",
                            "petites entreprises", "très petites entreprises"],
}


def normaliser(s: str) -> str:
    """Minuscule + suppression des accents pour un matching robuste."""
    return (
        unicodedata.normalize("NFKD", (s or "").lower())
        .encode("ascii", errors="ignore")
        .decode()
    )


def classifier_dimension(text: str) -> str | None:
    """Dimension IF dominante par matching de mots-clés, ou None."""
    tn = normaliser(text)
    scores = {d: 0 for d in KEYWORDS_DIMENSIONS}
    for dim, keywords in KEYWORDS_DIMENSIONS.items():
        for kw in keywords:
            if normaliser(kw) in tn:
                scores[dim] += 1
    meilleure = max(scores, key=scores.get)
    return meilleure if scores[meilleure] > 0 else None


def detecter_zone(text: str) -> str | None:
    """Zone géographique : pays CEMAC en priorité, puis Zone CEMAC / Afrique."""
    tn = normaliser(text)
    for zone, alias in _ZONE_ALIASES.items():
        if any(normaliser(a) in tn for a in alias):
            return zone
    if "cemac" in tn:
        return "Zone CEMAC"
    if "afrique" in tn or "africa" in tn:
        return "Afrique"
    return None


def detecter_cible(text: str) -> str | None:
    """Cible prioritaire dominante, ou None."""
    tn = normaliser(text)
    meilleure, meilleur_score = None, 0
    for cible, keywords in _CIBLE_KEYWORDS.items():
        score = sum(1 for kw in keywords if normaliser(kw) in tn)
        if score > meilleur_score:
            meilleure, meilleur_score = cible, score
    return meilleure


def classifier_article(titre: str, contenu: str = "") -> dict:
    """Retourne {dimension, zone, cible} pour un article (titre + contenu)."""
    texte = f"{titre or ''} {contenu or ''}"
    return {
        "dimension": classifier_dimension(texte),
        "zone":      detecter_zone(texte),
        "cible":     detecter_cible(texte),
    }
