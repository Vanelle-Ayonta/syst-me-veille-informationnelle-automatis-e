"""
scripts/generate_testset.py — Génération du jeu de test de référence (ground truth)

Construit un testset structuré à partir du corpus existant pour évaluer
le système RAG à 3 niveaux :
  - Niveau 1 (Retrieval)  : Precision@k, Recall@k, NDCG@k, MRR
  - Niveau 2 (RAG)        : Faithfulness, Answer Relevancy, Context Recall/Precision
  - Niveau 3 (Agentique)  : Tool call rate, trajectory correctness

Stratégie :
  1. Échantillonner des chunks couvrant les 6 dimensions IF et les 2 langues (FR/EN)
  2. Grouper par article (contexte cohérent)
  3. Générer des questions de 4 types via claude-haiku (cheap)
  4. Générer une réponse de référence ancrée sur les chunks sélectionnés
  5. Sauvegarder dans results/testset.json

Usage :
  python scripts/generate_testset.py
  python scripts/generate_testset.py --n 30 --par-dimension 5

Sorties :
  results/testset.json         — jeu de test complet
  results/testset_summary.txt  — résumé lisible
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import sys
import unicodedata
from datetime import datetime

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from dotenv import load_dotenv
load_dotenv()

# ─────────────────────────────────────────────────────────────────────────────
# Constantes
# ─────────────────────────────────────────────────────────────────────────────

RESULTS_DIR = os.path.join(_ROOT, "results")

DIMENSIONS_IF = [
    "Accès",
    "Utilisation",
    "Qualité",
    "Éducation financière",
    "Protection des consommateurs",
    "Innovation financière",
]

# Mots-clés par dimension (normalisés) — pour classifier les chunks échantillonnés
KEYWORDS_DIM: dict[str, list[str]] = {
    "Accès": [
        "acces", "access", "bancarisation", "compte bancaire", "bank account",
        "point de service", "agent bancaire", "rural", "non-bancarise",
        "unbanked", "underserved", "infrastructure financiere",
    ],
    "Utilisation": [
        "mobile money", "utilisation", "usage", "transaction", "paiement",
        "payment", "transfert", "remittance", "epargne", "savings",
        "credit", "emprunt", "loan",
    ],
    "Qualité": [
        "qualite", "quality", "fiabilite", "reliability", "satisfaction",
        "interoperabilite", "interoperability", "frais", "fees", "cout",
        "cost", "accessibilite", "affordability",
    ],
    "Éducation financière": [
        "education financiere", "financial literacy", "litteratie", "literacy",
        "sensibilisation", "awareness", "formation", "training",
        "connaissance financiere", "financial knowledge",
    ],
    "Protection des consommateurs": [
        "protection", "consommateur", "consumer", "fraude", "fraud",
        "securite", "security", "reclamation", "complaint", "regulation",
        "reglementation", "droits", "rights",
    ],
    "Innovation financière": [
        "fintech", "innovation", "digital", "numerique", "blockchain",
        "cbdc", "monnaie numerique", "open banking", "api", "startup",
        "technologie financiere", "financial technology",
    ],
}

TYPES_QUESTIONS = ["factuelle", "synthese", "comparative", "definition"]

# Prompt de génération de questions (haiku)
_PROMPT_QUESTIONS = """\
Tu es un expert en inclusion et innovation financières (zone CEMAC/Afrique).
À partir du texte ci-dessous, génère exactement {n_questions} questions en {langue} \
sur le thème : {dimension}.

Types de questions à produire (une de chaque si possible) :
- Factuelle : question précise avec réponse directe dans le texte
- Synthèse : question nécessitant d'articuler plusieurs éléments du texte
- Comparative : question comparant deux approches/pays/résultats
- Définition : question demandant d'expliquer un concept mentionné

CONTRAINTES STRICTES :
- Chaque question DOIT pouvoir être répondue à partir du texte fourni
- Questions spécifiques au domaine IF/BEAC/CEMAC — pas de généralités
- Formulation naturelle, comme poserait un analyste du DIIF
- Répondre UNIQUEMENT avec un objet JSON valide, aucun texte autour

Format de réponse (JSON strict) :
{{
  "questions": [
    {{"question": "...", "type": "factuelle|synthese|comparative|definition"}},
    ...
  ]
}}

TEXTE SOURCE :
{contexte}
"""

# Prompt de génération de réponse de référence (haiku)
_PROMPT_REFERENCE = """\
Tu es un analyste expert du DIIF/BEAC spécialisé en inclusion financière zone CEMAC.

Question : {question}

Texte source (seule base autorisée pour ta réponse) :
{contexte}

Rédige une réponse de référence factuelle et précise en {langue}, en :
- t'appuyant UNIQUEMENT sur le texte source ci-dessus
- citant les informations clés (chiffres, noms, dates si présents)
- restant concis : 80 à 150 mots maximum
- ne faisant AUCUNE supposition au-delà du texte

Réponse (texte direct, sans préambule) :
"""


# ─────────────────────────────────────────────────────────────────────────────
# Utilitaires
# ─────────────────────────────────────────────────────────────────────────────

def _norm(text: str) -> str:
    return (
        unicodedata.normalize("NFKD", (text or "").lower())
        .encode("ascii", errors="ignore")
        .decode()
    )


def _detecter_dimension(contenu: str, titre: str = "") -> str | None:
    """Détecte la dimension IF dominante d'un chunk par matching de mots-clés."""
    texte = _norm(titre + " " + contenu)
    scores = {dim: 0 for dim in DIMENSIONS_IF}
    for dim, kws in KEYWORDS_DIM.items():
        for kw in kws:
            if kw in texte:
                scores[dim] += 1
    meilleur = max(scores, key=scores.get)
    return meilleur if scores[meilleur] > 0 else None


def _build_llm():
    """Construit le client Anthropic (haiku — cheap pour la génération en masse)."""
    import anthropic
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY manquante dans .env")
    return anthropic.Anthropic(api_key=api_key)


def _appeler_haiku(client, prompt: str, max_tokens: int = 1024) -> str:
    """Appel synchrone à claude-haiku-4-5."""
    model = os.getenv("ANTHROPIC_MODEL_FAST", "claude-haiku-4-5-20251001")
    msg = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text.strip()


# ─────────────────────────────────────────────────────────────────────────────
# Échantillonnage du corpus
# ─────────────────────────────────────────────────────────────────────────────

def _echantillonner_chunks(par_dimension: int = 5) -> list[dict]:
    """
    Échantillonne des groupes de chunks représentatifs du corpus.
    Stratégie : pour chaque dimension IF × langue (FR/EN), sélectionner
    des articles avec suffisamment de chunks (≥ 2) pour former un contexte
    cohérent.

    Retourne une liste de dicts :
    {
        "dimension": str,
        "langue": str,
        "article_id": str,
        "titre": str,
        "source": str,
        "chunks": [{"id": str, "contenu": str, "position": int}]
        "contexte": str  # chunks concaténés
    }
    """
    import sqlite3

    db_path = os.path.join(_ROOT, "data", "veille_diif.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Récupérer tous les articles avec leurs chunks (≥ 2 chunks pour avoir
    # un contexte suffisant)
    rows = conn.execute("""
        SELECT
            a.id AS article_id,
            a.titre,
            a.langue,
            s.nom AS source_nom,
            COUNT(c.id) AS nb_chunks
        FROM articles a
        JOIN sources s ON a.source_id = s.id
        JOIN chunks c ON c.article_id = a.id
        WHERE a.contenu IS NOT NULL
          AND LENGTH(a.contenu) > 200
          AND a.qualite_contenu != 'hors_perimetre'
        GROUP BY a.id
        HAVING nb_chunks >= 2
        ORDER BY nb_chunks DESC
    """).fetchall()

    # Indexer par (dimension, langue)
    par_dim_langue: dict[tuple, list] = {}
    for r in rows:
        dim = _detecter_dimension(r["titre"] or "", "")
        if not dim:
            continue
        langue = (r["langue"] or "fr").lower()
        if langue not in ("fr", "en"):
            langue = "fr"
        key = (dim, langue)
        if key not in par_dim_langue:
            par_dim_langue[key] = []
        par_dim_langue[key].append(dict(r))

    # Échantillonner par dimension × langue
    groupes: list[dict] = []
    for dim in DIMENSIONS_IF:
        for langue in ("fr", "en"):
            key = (dim, langue)
            candidats = par_dim_langue.get(key, [])
            if not candidats:
                # Fallback : prendre n'importe quelle langue pour cette dimension
                alt_langue = "en" if langue == "fr" else "fr"
                candidats = par_dim_langue.get((dim, alt_langue), [])
                if candidats:
                    langue = alt_langue

            if not candidats:
                continue

            # Sélectionner aléatoirement (max par_dimension articles)
            selectionnes = random.sample(
                candidats, min(par_dimension, len(candidats))
            )

            for art in selectionnes:
                # Récupérer les chunks de cet article
                chunks = conn.execute("""
                    SELECT id, contenu, position
                    FROM chunks
                    WHERE article_id = ?
                    ORDER BY position
                    LIMIT 4
                """, (art["article_id"],)).fetchall()

                if not chunks:
                    continue

                chunk_list = [dict(c) for c in chunks]
                contexte = "\n\n".join(c["contenu"] for c in chunk_list)

                groupes.append({
                    "dimension":  dim,
                    "langue":     langue,
                    "article_id": art["article_id"],
                    "titre":      art["titre"] or "",
                    "source":     art["source_nom"] or "",
                    "chunks":     chunk_list,
                    "contexte":   contexte,
                })

    conn.close()

    # Mélanger pour varier l'ordre
    random.shuffle(groupes)
    return groupes


# ─────────────────────────────────────────────────────────────────────────────
# Génération des questions et réponses de référence
# ─────────────────────────────────────────────────────────────────────────────

def _generer_questions(client, groupe: dict, n_questions: int = 2) -> list[dict]:
    """
    Génère n_questions à partir du contexte d'un groupe de chunks.
    Retourne une liste de dicts {question, type}.
    """
    langue_label = "français" if groupe["langue"] == "fr" else "anglais"
    prompt = _PROMPT_QUESTIONS.format(
        n_questions=n_questions,
        langue=langue_label,
        dimension=groupe["dimension"],
        contexte=groupe["contexte"][:3000],
    )

    try:
        reponse = _appeler_haiku(client, prompt, max_tokens=512)
        # Extraire le JSON (robuste aux backticks markdown)
        if "```" in reponse:
            reponse = reponse.split("```")[1]
            if reponse.startswith("json"):
                reponse = reponse[4:]
        data = json.loads(reponse.strip())
        questions = data.get("questions", [])
        return [q for q in questions if isinstance(q, dict) and q.get("question")]
    except Exception as e:
        print(f"    [WARN] Génération questions échouée : {e}")
        return []


def _generer_reponse_reference(client, question: str, groupe: dict) -> str:
    """
    Génère une réponse de référence ancrée sur le contexte du groupe.
    """
    langue_label = "français" if groupe["langue"] == "fr" else "anglais"
    prompt = _PROMPT_REFERENCE.format(
        question=question,
        contexte=groupe["contexte"][:3000],
        langue=langue_label,
    )

    try:
        return _appeler_haiku(client, prompt, max_tokens=300)
    except Exception as e:
        print(f"    [WARN] Génération réponse référence échouée : {e}")
        return ""


# ─────────────────────────────────────────────────────────────────────────────
# Construction du testset
# ─────────────────────────────────────────────────────────────────────────────

def construire_testset(
    n_total: int = 30,
    par_dimension: int = 5,
    seed: int = 42,
) -> list[dict]:
    """
    Construit le testset complet.
    Retourne une liste de cas d'évaluation.
    """
    random.seed(seed)
    client = _build_llm()

    print(f"[INFO] Échantillonnage du corpus (par_dimension={par_dimension})...")
    groupes = _echantillonner_chunks(par_dimension=par_dimension)
    print(f"[INFO] {len(groupes)} groupes de chunks disponibles")

    # Calculer combien de questions par groupe pour atteindre n_total
    n_questions_par_groupe = max(1, round(n_total / max(len(groupes), 1)))
    n_questions_par_groupe = min(n_questions_par_groupe, 3)  # max 3 par groupe

    cases: list[dict] = []
    case_id = 0

    for i, groupe in enumerate(groupes):
        if len(cases) >= n_total:
            break

        print(f"  [{i+1}/{len(groupes)}] {groupe['dimension']} | "
              f"{groupe['langue'].upper()} | {groupe['source'][:30]} "
              f"— génération de {n_questions_par_groupe} question(s)...")

        questions = _generer_questions(client, groupe, n_questions_par_groupe)
        if not questions:
            print(f"    [SKIP] Aucune question générée")
            continue

        for q_data in questions:
            if len(cases) >= n_total:
                break

            question = q_data.get("question", "").strip()
            q_type = q_data.get("type", "factuelle")

            if not question:
                continue

            print(f"    → [{q_type}] {question[:70]}...")

            # Réponse de référence
            reference = _generer_reponse_reference(client, question, groupe)

            case_id += 1
            cases.append({
                "id": f"case_{case_id:03d}",
                "question": question,
                "reference_answer": reference,
                "question_type": q_type,
                "dimension": groupe["dimension"],
                "langue": groupe["langue"],
                "source": groupe["source"],
                "article_id": groupe["article_id"],
                "titre_article": groupe["titre"],
                "relevant_chunk_ids": [c["id"] for c in groupe["chunks"]],
                "contexte_reference": groupe["contexte"][:2000],
            })

    return cases


# ─────────────────────────────────────────────────────────────────────────────
# Sauvegarde et résumé
# ─────────────────────────────────────────────────────────────────────────────

def sauvegarder(cases: list[dict], chemin: str) -> None:
    testset = {
        "metadata": {
            "date_generation": datetime.now().isoformat(),
            "n_cases": len(cases),
            "dimensions_couvertes": list({c["dimension"] for c in cases}),
            "langues": list({c["langue"] for c in cases}),
            "types_questions": list({c["question_type"] for c in cases}),
            "description": (
                "Jeu de test de référence pour l'évaluation du système RAG agentique SVIA. "
                "Généré automatiquement depuis le corpus via claude-haiku. "
                "Chaque cas contient une question, une réponse de référence ancrée sur "
                "le corpus, et les chunk_ids pertinents (ground truth retrieval)."
            ),
        },
        "cases": cases,
    }
    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    with open(chemin, "w", encoding="utf-8") as f:
        json.dump(testset, f, ensure_ascii=False, indent=2)
    print(f"\n[OK] Testset sauvegardé : {chemin}")


def afficher_resume(cases: list[dict]) -> None:
    print("\n" + "═" * 60)
    print("RÉSUMÉ DU TESTSET")
    print("═" * 60)
    print(f"Total questions : {len(cases)}")

    # Par dimension
    print("\nPar dimension IF :")
    dims = {}
    for c in cases:
        dims[c["dimension"]] = dims.get(c["dimension"], 0) + 1
    for dim, n in sorted(dims.items(), key=lambda x: -x[1]):
        print(f"  {dim:<35} : {n}")

    # Par type
    print("\nPar type de question :")
    types = {}
    for c in cases:
        types[c["question_type"]] = types.get(c["question_type"], 0) + 1
    for t, n in sorted(types.items(), key=lambda x: -x[1]):
        print(f"  {t:<15} : {n}")

    # Par langue
    print("\nPar langue :")
    langs = {}
    for c in cases:
        langs[c["langue"]] = langs.get(c["langue"], 0) + 1
    for l, n in langs.items():
        print(f"  {l.upper()} : {n}")

    print("\nExemples de questions générées :")
    for c in cases[:5]:
        print(f"  [{c['dimension']}] {c['question']}")

    print("═" * 60)


# ─────────────────────────────────────────────────────────────────────────────
# Point d'entrée
# ─────────────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Génère le jeu de test de référence pour l'évaluation RAG.")
    parser.add_argument(
        "--n", type=int, default=30,
        help="Nombre total de questions à générer (défaut: 30)")
    parser.add_argument(
        "--par-dimension", type=int, default=5,
        help="Nb d'articles échantillonnés par dimension IF (défaut: 5)")
    parser.add_argument(
        "--seed", type=int, default=42,
        help="Graine aléatoire pour la reproductibilité (défaut: 42)")
    parser.add_argument(
        "--output", type=str,
        default=os.path.join(RESULTS_DIR, "testset.json"),
        help="Chemin de sortie du fichier JSON")
    args = parser.parse_args()

    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("[ERREUR] ANTHROPIC_API_KEY manquante dans .env")
        return 1

    print(f"[INFO] Génération du testset — n={args.n}, "
          f"par_dimension={args.par_dimension}, seed={args.seed}")

    cases = construire_testset(
        n_total=args.n,
        par_dimension=args.par_dimension,
        seed=args.seed,
    )

    if not cases:
        print("[ERREUR] Aucun cas généré — vérifier le corpus et la DB.")
        return 1

    afficher_resume(cases)
    sauvegarder(cases, args.output)

    # Résumé texte lisible
    summary_path = args.output.replace(".json", "_summary.txt")
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write(f"Testset SVIA — {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
        f.write(f"Total : {len(cases)} questions\n\n")
        for c in cases:
            f.write(f"[{c['id']}] [{c['dimension']}] [{c['question_type']}]\n")
            f.write(f"Q: {c['question']}\n")
            f.write(f"R: {c['reference_answer'][:200]}...\n")
            f.write(f"Chunks: {', '.join(c['relevant_chunk_ids'])}\n\n")
    print(f"[OK] Résumé lisible : {summary_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
