"""
core/rag/indexer.py — Gestion de l'index FAISS scalable
Stratégie adaptative selon le volume :
  < 100 000 vecteurs : IndexFlatL2  (exact, rapide)
  ≥ 100 000 vecteurs : IndexIVFFlat (approximatif, scalable)

Lazy loading — l'index n'est chargé qu'à la première recherche.
Incrémental — seuls les chunks sans faiss_id sont indexés.
Reconstruction hebdomadaire — via le scheduler.
"""
import os, sys, logging
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
from config import FAISS_INDEX_PATH
from core.database import get_db, now_iso

log = logging.getLogger(__name__)

FAISS_BIN      = FAISS_INDEX_PATH + ".bin"
FAISS_IDS_FILE = FAISS_INDEX_PATH + "_ids.npy"
SEUIL_IVF      = 100_000   # basculer vers IVFFlat au-delà
MICRO_BATCH    = 256        # chunks traités par lot d'embedding

_index     = None
_chunk_ids = None


def _ensure_dir():
    os.makedirs(os.path.dirname(FAISS_INDEX_PATH), exist_ok=True)


def _creer_index_vide(dim: int, ntotal: int = 0):
    """Crée le bon type d'index selon le volume attendu."""
    import faiss
    if ntotal < SEUIL_IVF:
        log.info("[INDEXER] Type : IndexFlatL2 (exact)")
        return faiss.IndexFlatL2(dim)
    else:
        log.info("[INDEXER] Type : IndexIVFFlat (scalable)")
        quantizer = faiss.IndexFlatL2(dim)
        index = faiss.IndexIVFFlat(quantizer, dim, 256)
        return index


def get_index(force_reload: bool = False):
    """Charge l'index FAISS en mémoire (lazy)."""
    global _index, _chunk_ids

    if _index is not None and not force_reload:
        return _index, _chunk_ids

    import faiss
    from core.rag.embedder import get_dim

    _ensure_dir()
    dim = get_dim()

    if os.path.exists(FAISS_BIN) and os.path.exists(FAISS_IDS_FILE):
        log.info("[INDEXER] Chargement index existant...")
        _index     = faiss.read_index(FAISS_BIN)
        _chunk_ids = np.load(
            FAISS_IDS_FILE, allow_pickle=True
        ).tolist()
        log.info(f"[INDEXER] {_index.ntotal} vecteurs chargés.")
    else:
        log.info("[INDEXER] Création nouvel index...")
        _index     = _creer_index_vide(dim)
        _chunk_ids = []

    return _index, _chunk_ids


def sauvegarder_index():
    """Persiste l'index sur disque."""
    import faiss
    if _index is None:
        return
    _ensure_dir()
    faiss.write_index(_index, FAISS_BIN)
    np.save(FAISS_IDS_FILE,
            np.array(_chunk_ids, dtype=object))
    taille_mo = os.path.getsize(FAISS_BIN) / (1024 * 1024)
    log.info(f"[INDEXER] Sauvegardé — {_index.ntotal} vecteurs "
             f"({taille_mo:.1f} Mo)")


def indexer_chunks_nouveaux() -> dict:
    """
    Indexe uniquement les chunks sans faiss_id.
    Traitement par micro-batches — scalable.
    Reprend automatiquement si interrompu.
    """
    from core.rag.embedder import embed_chunks_list

    index, chunk_ids = get_index()
    total_indexe = 0

    while True:
        # Micro-batch de chunks non indexés
        with get_db() as conn:
            rows = conn.execute("""
                SELECT id, contenu FROM chunks
                WHERE faiss_id IS NULL
                  AND contenu IS NOT NULL
                  AND LENGTH(contenu) >= 50
                ORDER BY rowid
                LIMIT ?
            """, (MICRO_BATCH,)).fetchall()

        if not rows:
            break

        ids    = [r["id"]      for r in rows]
        textes = [r["contenu"] for r in rows]

        # Génération des embeddings
        try:
            embeddings = embed_chunks_list(textes).astype(np.float32)
        except Exception as e:
            log.error(f"[INDEXER] Erreur embedding : {e}")
            break

        # Vérifier si IVFFlat doit être entraîné
        if (hasattr(index, 'is_trained') and
                not index.is_trained):
            if len(chunk_ids) + len(rows) >= 256:
                log.info("[INDEXER] Entraînement IVFFlat...")
                index.train(embeddings)
            else:
                log.warning("[INDEXER] Pas assez de données pour "
                            "entraîner IVFFlat — report")
                break

        debut_pos = len(chunk_ids)
        index.add(embeddings)

        # Mise à jour en base
        with get_db() as conn:
            for i, chunk_id in enumerate(ids):
                faiss_pos = debut_pos + i
                chunk_ids.append(chunk_id)
                conn.execute("""
                    UPDATE chunks
                    SET faiss_id = ?, indexe_le = ?
                    WHERE id = ?
                """, (faiss_pos, now_iso(), chunk_id))

        total_indexe += len(rows)
        # Sauvegarde DURABLE après chaque micro-batch : si le process est
        # interrompu (veille, kill…), la progression est conservée et un simple
        # relancement reprend là où il s'était arrêté (chunks faiss_id NULL).
        sauvegarder_index()
        log.info(f"[INDEXER] {total_indexe} chunks indexés "
                 f"(total index : {index.ntotal}) — sauvegardé")

    sauvegarder_index()
    return {
        "indexés":     total_indexe,
        "total_index": index.ntotal,
    }


def reconstruire_index_complet() -> dict:
    """
    Reconstruit l'index FAISS depuis zéro.
    À appeler hebdomadairement via le scheduler.
    Garantit la cohérence index ↔ base.
    """
    global _index, _chunk_ids
    import faiss
    from core.rag.embedder import get_dim, embed_chunks_list

    log.info("[INDEXER] Reconstruction complète de l'index...")

    # Remettre tous les faiss_id à NULL
    with get_db() as conn:
        conn.execute(
            "UPDATE chunks SET faiss_id = NULL, indexe_le = NULL"
        )

    # Recréer l'index vide
    dim = get_dim()
    with get_db() as conn:
        ntotal = conn.execute(
            "SELECT COUNT(*) FROM chunks WHERE contenu != ''"
        ).fetchone()[0]

    _index     = _creer_index_vide(dim, ntotal)
    _chunk_ids = []
    sauvegarder_index()

    # Réindexer tout
    stats = indexer_chunks_nouveaux()
    log.info(f"[INDEXER] Reconstruction terminée — "
             f"{stats['total_index']} vecteurs")
    return stats


def decharger_index():
    """Libère l'index de la mémoire RAM."""
    global _index, _chunk_ids
    _index     = None
    _chunk_ids = None
    log.info("[INDEXER] Index déchargé de la mémoire.")


def get_stats_index() -> dict:
    """Statistiques sans charger l'index si absent."""
    if _index is not None:
        ntotal = _index.ntotal
    elif os.path.exists(FAISS_BIN):
        import faiss
        idx    = faiss.read_index(FAISS_BIN)
        ntotal = idx.ntotal
        del idx
    else:
        return {
            "total_vecteurs": 0,
            "index_existe":   False,
            "taille_mo":      0,
        }

    return {
        "total_vecteurs": ntotal,
        "index_existe":   True,
        "taille_mo": round(
            os.path.getsize(FAISS_BIN) / (1024 * 1024), 2
        ) if os.path.exists(FAISS_BIN) else 0,
        "en_memoire": _index is not None,
    }
