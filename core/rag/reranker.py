"""
core/rag/reranker.py — Reranking cross-encoder (étape 2b)

Après le retrieval vectoriel FAISS (similarité cosinus sur embeddings denses),
le cross-encoder re-score chaque paire (requête, chunk) en les lisant ensemble,
ce qui donne une mesure de pertinence beaucoup plus fine.

Modèle : cross-encoder/mmarco-mMiniLMv2-L12-H384-v1
  - Multilingue (50 langues dont FR et EN)
  - Léger : ~135 MB, tourne sur CPU en < 1s pour 16 candidats
  - Entraîné sur MS MARCO multilingue → bon pour la recherche documentaire

Pourquoi un cross-encoder après FAISS ?
  FAISS encode requête et documents SÉPARÉMENT puis compare leurs vecteurs.
  C'est rapide mais approximatif : deux phrases sémantiquement proches dans
  l'espace d'embedding peuvent ne pas être pertinentes l'une pour l'autre.
  Le cross-encoder les LIT ENSEMBLE (requête + chunk dans un seul passage au
  modèle), ce qui lui permet de capturer les interactions lexicales fines
  (négations, chiffres précis, noms propres) que l'embedding rate.

Architecture du pipeline de retrieval avec reranker :
  1. FAISS : retrieval rapide, top_k × 2 candidats (rappel élevé)
  2. Cross-encoder : re-scoring précis, sélection top_k final (précision élevée)
  3. Reranking longueur (existant) : boost léger sur chunks longs bien répondants

Lazy loading thread-safe : le modèle n'est chargé qu'au premier appel
(même pattern que embedder.py).
"""
import logging
import os
import threading
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

log = logging.getLogger(__name__)

_model   = None
_lock    = threading.Lock()
_enabled = None   # None = pas encore vérifié


def _is_enabled() -> bool:
    """Lit USE_RERANKER depuis config (une seule fois)."""
    global _enabled
    if _enabled is None:
        try:
            from config import USE_RERANKER
            _enabled = USE_RERANKER
        except Exception:
            _enabled = True
    return _enabled


def get_reranker():
    """
    Singleton lazy thread-safe du cross-encoder.
    Retourne None si le reranker est désactivé ou si le modèle est indisponible.
    """
    global _model
    if not _is_enabled():
        return None
    if _model is None:
        with _lock:
            if _model is None:
                try:
                    from sentence_transformers import CrossEncoder
                    from config import RERANKER_MODEL
                    cache = os.environ.get(
                        "SENTENCE_TRANSFORMERS_HOME",
                        os.path.join(os.path.dirname(os.path.dirname(
                            os.path.dirname(os.path.abspath(__file__))
                        )), "model_cache")
                    )
                    log.info(f"[RERANKER] Chargement {RERANKER_MODEL}...")
                    m = CrossEncoder(
                        RERANKER_MODEL,
                        cache_folder=cache,
                        max_length=512,
                    )
                    log.info("[RERANKER] Modèle chargé.")
                    _model = m
                except Exception as e:
                    log.warning(
                        f"[RERANKER] Chargement impossible ({e}). "
                        "Le reranking cross-encoder est désactivé pour cette session."
                    )
                    _model = "unavailable"
    return None if _model == "unavailable" else _model


def reranker_chunks(query: str, chunks: list, top_k: int) -> list:
    """
    Re-score les chunks candidats avec le cross-encoder et retourne les top_k
    les plus pertinents pour la requête.

    Paramètres
    ----------
    query  : requête utilisateur (enrichie ou originale)
    chunks : liste de dicts retournés par rechercher() — contiennent 'contenu'
             et 'score' (score FAISS converti en similarité cosinus)
    top_k  : nombre de chunks à retourner après reranking

    Retourne
    --------
    Liste de chunks triés par score cross-encoder décroissant, taille ≤ top_k.
    Chaque chunk conserve son score FAISS original dans 'score_faiss' et reçoit
    le score cross-encoder dans 'score' (pour la compatibilité downstream).

    Comportement de fallback
    ------------------------
    Si le reranker est indisponible (modèle non chargé, USE_RERANKER=false),
    retourne les chunks inchangés tronqués à top_k — sans lever d'exception.
    """
    if not chunks:
        return chunks

    reranker = get_reranker()

    # Fallback : reranker indisponible → retour sans modification
    if reranker is None:
        log.debug("[RERANKER] Désactivé — retour sans reranking.")
        return chunks[:top_k]

    try:
        # Construire les paires (requête, contenu_chunk)
        paires = [(query, c.get("contenu", "")[:512]) for c in chunks]

        # Score cross-encoder : logit brut (non normalisé, comparable en rang)
        scores = reranker.predict(paires)

        # Enrichir chaque chunk avec les deux scores
        for chunk, ce_score in zip(chunks, scores):
            chunk["score_faiss"]   = round(chunk.get("score", 0), 4)
            chunk["score"]         = round(float(ce_score), 4)
            chunk["score_ce_raw"]  = round(float(ce_score), 4)

        # Trier par score cross-encoder décroissant
        chunks.sort(key=lambda x: x["score"], reverse=True)

        log.info(
            f"[RERANKER] {len(chunks)} → top {top_k} | "
            f"scores CE : min={min(scores):.2f}, max={max(scores):.2f}"
        )
        return chunks[:top_k]

    except Exception as e:
        log.warning(f"[RERANKER] Reranking échoué ({e}) — fallback FAISS.")
        # Restaurer les scores FAISS si on avait commencé à les écraser
        for chunk in chunks:
            if "score_faiss" in chunk:
                chunk["score"] = chunk["score_faiss"]
        return chunks[:top_k]
