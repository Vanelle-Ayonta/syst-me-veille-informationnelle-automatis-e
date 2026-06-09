"""
core/guardrails.py — Guardrails de sécurité du SVIA
Protège le système contre les injections, les requêtes hors périmètre,
les tentatives d'extraction de données sensibles, et valide les sorties.
S'applique en entrée (avant l'agent) et en sortie (après l'agent).
"""
from __future__ import annotations

import re
import unicodedata

from pydantic import BaseModel


# ──────────────────────────────────────────────────────────────────────────────
# Modèle de résultat
# ──────────────────────────────────────────────────────────────────────────────

class GuardrailResult(BaseModel):
    """Résultat d'une vérification guardrail."""

    ok: bool
    message_erreur: str | None = None
    reponse_nettoyee: str | None = None
    guardrail_declenche: str | None = None


# ──────────────────────────────────────────────────────────────────────────────
# Utilitaires
# ──────────────────────────────────────────────────────────────────────────────

def _norm(text: str) -> str:
    """Normalise un texte : minuscules + suppression des diacritiques."""
    return (
        unicodedata.normalize("NFKD", text.lower())
        .encode("ascii", errors="ignore")
        .decode()
    )


# ──────────────────────────────────────────────────────────────────────────────
# Guardrail 1 — Prompt injection
# ──────────────────────────────────────────────────────────────────────────────

_INJECTION_PATTERNS: list[str] = [
    # Ordre d'oubli / reset d'instructions
    r"ignore\s+(previous|tes|les|all|my|your)?\s*(previous\s+)?instructions?",
    r"oublie\s+(tout|tes\s+instructions|les\s+instructions)",
    r"forget\s+(everything|all|your|previous|instructions?)",
    r"disregard\s+(previous|all|any|your)?\s*(instructions?|context|rules?)?",
    # Redéfinition d'identité
    r"tu\s+es\s+maintenant",
    r"you\s+are\s+now",
    r"nouveau\s+r[oô]le",
    r"new\s+role",
    r"change\s+(ton|votre|your)\s+r[oô]le",
    # Jailbreak classiques
    r"jailbreak",
    r"act\s+as(\s+if)?",
    r"pretend\s+(you\s+are|to\s+be)",
    r"simule\s+(que\s+tu\s+es|un|une)",
    r"imagine\s+(que\s+tu\s+es|you\s+are)",
    # Balises système injectées
    r"<\s*/?system\s*>",
    r"\[INST\]",
    r"###\s*(system|instruction|prompt|role)",
    r"\[SYSTEM\]",
    r"<\s*/?s\s*>",
    # Répétition / révélation du prompt système
    r"r[eé]p[eè]te\s+(ton|votre|le|du)\s+(prompt|syst[eè]me|instruction)",
    r"(show|display|print|reveal|repeat)\s+(your|the|me\s+the)\s+(system\s+)?prompt",
    r"(montre|affiche|r[eé]v[eè]le)[sz]?\s+(moi|nous)?\s*.{0,25}(prompt|syst[eè]me|instruction)",
    # DAN / mode alternatif
    r"\bDAN\b",
    r"developer\s+mode",
    r"mode\s+développeur",
    r"bypass\s+(your\s+)?(safeguards?|filter|restriction)",
    r"contourne\s+(tes|vos)\s+(protections?|restrictions?|filtres?)",
]

_INJECTION_RE = [re.compile(p, re.IGNORECASE) for p in _INJECTION_PATTERNS]


def _check_injection(question: str) -> bool:
    """Retourne True si une tentative d'injection est détectée."""
    # Vérification sur le texte original ET normalisé (sans accents)
    q_norm = _norm(question)
    for rx in _INJECTION_RE:
        if rx.search(question) or rx.search(q_norm):
            return True
    return False


# ──────────────────────────────────────────────────────────────────────────────
# Guardrail 2 — Hors périmètre
# ──────────────────────────────────────────────────────────────────────────────

# Mots-clés qui signalent clairement un sujet hors périmètre
_HORS_PERIMETRE: list[str] = [
    # Sport
    "coupe du monde", "world cup", "coupe d'afrique", "can ", " can 20",
    "champions league", "ligue des champions",
    "match de football", "match de tennis", "match de basket",
    "score du match", "resultat du match", "résultat du match",
    "joueur de football", "transfert de joueur",
    "formule 1", "moto gp", "tour de france",
    # Cuisine
    "recette de", "comment cuisiner", "comment faire un gateau",
    "gastronomie", "chef cuisinier", "restaurant gastronomique",
    # Météo (non financière)
    "previsions meteo", "prévisions météo", "quel temps fait",
    "temperature demain", "température demain",
    "bulletin meteo", "bulletin météo",
    # Divertissement
    "serie televisee", "série télévisée", "netflix original",
    "jeu video", "jeu vidéo", "gaming pc",
    "meilleur film", "dernier film de", "concert de",
    # Politique non-financière
    "resultat election", "résultat élection", "qui a gagne l election",
    "taux de vote", "bureau de vote",
    # Trivial
    "horoscope", "astrologie", "signe du zodiaque",
    "blague", "histoire drole", "histoire drôle",
]

# Mots-clés qui signalent un sujet dans le périmètre IF/finance
_IN_SCOPE: list[str] = [
    # Institutions
    "beac", "cemac", "diif", "bceao", "uemoa", "imf", "fmi",
    "banque mondiale", "world bank", "bis ", " bis",
    "banque centrale", "central bank", "banque de france",
    # Finance / IF
    "inclusion financiere", "inclusion financière", "financial inclusion",
    "mobile money", "fintech", "microfinance", "microassurance",
    "bancarisation", "banque", "bancaire", "banking",
    "credit", "crédit", "epargne", "épargne", "depot", "dépôt",
    "paiement", "payment", "transfert", "monnaie", "currency",
    "investissement", "investment", "assurance", "insurance",
    "microcredit", "microcrédit",
    # Finance numérique
    "digital finance", "finance numerique", "finance numérique",
    "innovation financiere", "innovation financière",
    "open banking", "blockchain", "cbdc", "crypto monnaie",
    "portefeuille electronique", "portefeuille électronique",
    "monnaie electronique", "monnaie électronique",
    # Dimensions IF
    "acces financier", "accès financier", "utilisation financiere",
    "education financiere", "éducation financière",
    "protection du consommateur", "litteratie financiere",
    "littératie financière",
    # Économie
    "taux d interet", "taux d'intérêt", "taux de change",
    "inflation", "economie", "économie", "fiscal", "monetaire",
    "monétaire", "macroeconomie", "macroéconomie",
    # Géographie IF
    "afrique", "africa", "cameroun", "congo", "gabon",
    "tchad", "rca", "guinee equatoriale", "guinée équatoriale",
    "zone cemac", "region cemac",
    # Produits financiers
    "compte courant", "compte epargne", "compte épargne",
    "virement bancaire", "agent bancaire", "point de service",
    "remittance", "transfert d argent",
]


def _check_hors_perimetre(question: str) -> bool:
    """
    Retourne True si la question est clairement hors périmètre.
    Logique : signal hors-périmètre présent ET aucun ancrage financier.
    """
    q_norm = _norm(question)
    has_hors = any(_norm(kw) in q_norm for kw in _HORS_PERIMETRE)
    has_scope = any(_norm(kw) in q_norm for kw in _IN_SCOPE)
    return has_hors and not has_scope


# ──────────────────────────────────────────────────────────────────────────────
# Guardrail 3 — Confidentialité
# ──────────────────────────────────────────────────────────────────────────────

_CONFIDENTIALITY_PATTERNS: list[str] = [
    # Mots de passe
    r"(mot\s+de\s+passe|password|passwd|mdp\b)",
    # Clés API / tokens
    r"(api[\s_\-]?key|clef?\s+api|cl[eé]\s+api|api\s+token)",
    r"(secret[\s_\-]?key|secret\s+token|bearer\s+token|access\s+token)",
    r"(anthropic[\s_]?api|openai[\s_]?key|sk\-[a-z])",
    # Données personnelles agents
    r"(donn[eé]es?\s+personnelles?|personal\s+data|pii\b|gdpr)",
    r"(identifiant\s+agent|login\s+agent|nom\s+d.utilisateur)",
    r"(liste\s+des?\s+utilisateurs?|liste\s+des?\s+agents?)",
    # Configuration système
    r"(configuration\s+syst[eè]me|system\s+(config|settings|setup))",
    r"(variables?\s+d.environnement|\.env\b|env\s+var)",
    # Base de données directe
    r"(base\s+de\s+donn[eé]es?|database|sqlite|\.db\b)",
    r"\b(select|insert|update|delete|drop|create)\b.{0,30}\b(from|into|table)\b",
    # Prompt système
    r"(prompt\s+syst[eè]me|system\s+prompt|instruction\s+syst[eè]me)",
    r"(contenu\s+de\s+(ton|votre|le|du)\s+(prompt|syst[eè]me|instruction))",
    r"(montre|affiche|donne|r[eé]v[eè]le)[sz]?\s+(moi|nous)?\s*.{0,30}"
    r"(prompt|instruction|config|syst[eè]me)",
    # Index FAISS / fichiers internes
    r"(faiss|index\s+vectoriel|embeddings?\s+model)",
    r"(chemin\s+du\s+fichier|file\s+path|repertoire\s+interne|répertoire\s+interne)",
]

_CONFIDENTIALITY_RE = [re.compile(p, re.IGNORECASE) for p in _CONFIDENTIALITY_PATTERNS]


def _check_confidentiality(question: str) -> bool:
    """Retourne True si tentative d'extraction de données sensibles détectée."""
    for rx in _CONFIDENTIALITY_RE:
        if rx.search(question):
            return True
    return False


# ──────────────────────────────────────────────────────────────────────────────
# Guardrail 4 — Validation des sorties
# ──────────────────────────────────────────────────────────────────────────────

# Patterns de secrets à masquer dans les réponses
_SECRET_PATTERNS: list[str] = [
    r"sk[-_][a-zA-Z0-9\-_]{20,}",          # Anthropic / OpenAI key (avec dashes)
    r"Bearer\s+[a-zA-Z0-9\-._~+/]{20,}",
    r"api[_\s\-]?key\s*[:=]\s*[a-zA-Z0-9\-_]{16,}",
    r"ANTHROPIC_API_KEY\s*[=:]\s*\S+",
    r"OPENAI_API_KEY\s*[=:]\s*\S+",
    r"APP_SECRET_KEY\s*[=:]\s*\S+",
]
_SECRET_RE = [re.compile(p, re.IGNORECASE) for p in _SECRET_PATTERNS]

# Fragments distinctifs du prompt système — variantes accentuées ET normalisées
_SYSTEM_PROMPT_FRAGMENTS = [
    "Système de Veille Informationnelle Automatisée",
    "Systeme de Veille Informationnelle Automatisee",
    "Processus de réponse",
    "Processus de reponse",
    "Appelle search_corpus",
    "Règles impératives",
    "Regles imperatives",
    "RÈGLE 1 — SALUTATIONS",
    "REGLE 1 - SALUTATIONS",
    "RÈGLE ABSOLUE SUR LES SALUTATIONS",
    "REGLE ABSOLUE SUR LES SALUTATIONS",
]

_SALUTATIONS_ENTREE = {
    "bonjour", "bonsoir", "salut", "hello", "hi",
    "bonne journée", "bonne journee", "hey", "coucou",
}

# Indicateurs de langue pour détecter l'anglais vs français
_FR_WORDS = {"le", "la", "les", "de", "du", "des", "un", "une", "est",
             "sont", "dans", "pour", "avec", "sur", "par", "que", "qui"}
_EN_WORDS = {"the", "is", "are", "and", "in", "of", "to", "for",
             "with", "on", "by", "that", "this", "have", "from"}


def _is_english(text: str) -> bool:
    """Détecte si un texte est majoritairement en anglais."""
    words = set(re.findall(r"\b\w+\b", text.lower()))
    en_count = len(words & _EN_WORDS)
    fr_count = len(words & _FR_WORDS)
    return en_count > fr_count and en_count >= 3


def _check_output(reponse: str, question: str) -> tuple[bool, str, str | None]:
    """
    Vérifie et nettoie la réponse.
    Retourne (ok, reponse_nettoyee, guardrail_declenche).
    """
    cleaned = reponse

    # Détection salutation : le minimum de longueur ne s'applique pas
    q_lower = question.lower().strip()
    est_salutation = (
        any(s in q_lower for s in _SALUTATIONS_ENTREE)
        and len(q_lower) < 30
    )

    # Longueur minimum (ignorée pour les salutations)
    if not est_salutation and len(cleaned.strip()) < 50:
        return False, cleaned, "validation_sortie_longueur"

    # Masquage des secrets éventuels
    for rx in _SECRET_RE:
        cleaned = rx.sub("[REDACTED]", cleaned)

    # Détection de fuite du prompt système
    for fragment in _SYSTEM_PROMPT_FRAGMENTS:
        if fragment.lower() in cleaned.lower():
            cleaned = re.sub(
                re.escape(fragment),
                "[contenu système masqué]",
                cleaned,
                flags=re.IGNORECASE,
            )

    # Vérification de la langue (réponse en français sauf question en anglais)
    if not _is_english(question) and _is_english(cleaned):
        # On laisse passer mais on pourrait alerter — pas de blocage car
        # le modèle peut légitimement citer des sources en anglais
        pass

    return True, cleaned, None


# ──────────────────────────────────────────────────────────────────────────────
# API publique
# ──────────────────────────────────────────────────────────────────────────────

def verifier_entree(question: str) -> GuardrailResult:
    """
    Vérifie la question AVANT l'appel à l'agent.
    Applique dans l'ordre : injection → confidentialité → hors périmètre.
    Retourne GuardrailResult(ok=True) si la question peut être traitée.
    """
    if not question or not question.strip():
        return GuardrailResult(
            ok=False,
            message_erreur="La question ne peut pas être vide.",
            guardrail_declenche="validation_entree",
        )

    # 1. Prompt injection (priorité maximale)
    if _check_injection(question):
        return GuardrailResult(
            ok=False,
            message_erreur=(
                "Cette requête a été bloquée : elle semble tenter de "
                "manipuler le comportement du système."
            ),
            guardrail_declenche="prompt_injection",
        )

    # 2. Confidentialité (avant hors-périmètre car plus critique)
    if _check_confidentiality(question):
        return GuardrailResult(
            ok=False,
            message_erreur=(
                "Je ne peux pas répondre à cette demande. "
                "Les informations sensibles du système (mots de passe, "
                "clés API, données personnelles, configuration) "
                "sont protégées."
            ),
            guardrail_declenche="confidentialite",
        )

    # 3. Hors périmètre
    if _check_hors_perimetre(question):
        return GuardrailResult(
            ok=False,
            message_erreur=(
                "Je suis spécialisé dans l'inclusion et l'innovation "
                "financières en zone CEMAC. "
                "Je ne peux pas répondre à cette question."
            ),
            guardrail_declenche="hors_perimetre",
        )

    return GuardrailResult(ok=True)


def verifier_sortie(reponse: str, question: str) -> GuardrailResult:
    """
    Vérifie et nettoie la réponse de l'agent APRÈS sa génération.
    Applique le guardrail de validation des sorties.
    Retourne toujours une reponse_nettoyee (éventuellement identique à l'originale).
    """
    ok, cleaned, guardrail = _check_output(reponse, question)

    if not ok:
        return GuardrailResult(
            ok=False,
            message_erreur=(
                "La réponse générée ne satisfait pas les critères de qualité. "
                "Veuillez reformuler votre question."
            ),
            reponse_nettoyee=None,
            guardrail_declenche=guardrail or "validation_sortie",
        )

    return GuardrailResult(
        ok=True,
        reponse_nettoyee=cleaned,
        guardrail_declenche=None,
    )
