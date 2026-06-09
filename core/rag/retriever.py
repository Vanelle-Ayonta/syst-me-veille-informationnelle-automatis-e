"""
core/rag/retriever.py — Recherche sémantique
Retourne les chunks les plus pertinents pour une requête.
Filtres post-recherche : langue, source, dimension IF.
"""
import os, sys, logging
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
from core.database import get_db

log = logging.getLogger(__name__)


def rechercher(query: str,
               top_k: int = 10,
               filtre_langue: str = None,
               filtre_source_ids: list = None,
               filtre_dimension: str = None) -> list:
    """
    Recherche sémantique dans l'index FAISS.
    Retourne les top_k chunks les plus pertinents.

    Paramètres
    ----------
    query             : requête en langage naturel FR ou EN
    top_k             : nombre de résultats souhaités
    filtre_langue     : 'fr' | 'en' | None
    filtre_source_ids : liste de source_id | None
    filtre_dimension  : dimension IF | None
    """
    from core.rag.embedder import embed_query
    from core.rag.indexer  import get_index

    index, chunk_ids = get_index()

    if index.ntotal == 0:
        log.warning("[RETRIEVER] Index vide — lancez le pipeline RAG.")
        return []

    query_vec = embed_query(query).astype(np.float32).reshape(1, -1)

    # Chercher plus que top_k pour absorber les filtrages
    k_search  = min(top_k * 8, index.ntotal)
    distances, indices = index.search(query_vec, k_search)

    # Collecter les (chunk_id, distance) valides en une passe
    candidats = []
    for dist, idx in zip(distances[0], indices[0]):
        if idx < 0 or idx >= len(chunk_ids):
            continue
        candidats.append((chunk_ids[int(idx)], float(dist)))

    if not candidats:
        return []

    # Une seule connexion pour récupérer tous les chunks d'un coup
    ids_sql = [c[0] for c in candidats]
    placeholders = ",".join("?" * len(ids_sql))

    with get_db() as conn:
        rows = conn.execute(f"""
            SELECT
                c.id          AS chunk_id,
                c.contenu,
                c.position,
                a.id          AS article_id,
                a.titre,
                a.url_original,
                a.publie_le,
                a.collecte_le,
                a.langue,
                s.nom         AS source_nom,
                s.id          AS source_id
            FROM chunks c
            LEFT JOIN articles a ON c.article_id = a.id
            LEFT JOIN sources  s ON a.source_id  = s.id
            WHERE c.id IN ({placeholders})
        """, ids_sql).fetchall()

    # Index rows par chunk_id pour retrouver la distance FAISS
    rows_by_id = {dict(r)["chunk_id"]: dict(r) for r in rows}

    resultats = []
    for chunk_id, dist in candidats:
        row = rows_by_id.get(chunk_id)
        if not row:
            continue

        # Filtres post-recherche
        if filtre_langue and row.get("langue") != filtre_langue:
            continue
        if filtre_source_ids and row.get("source_id") not in filtre_source_ids:
            continue

        score = float(1 / (1 + dist))
        resultats.append({**row, "score": score, "distance": dist})

        if len(resultats) >= top_k:
            break

    return resultats


def formater_contexte(chunks: list,
                      max_chars: int = 16000) -> str:
    """
    Formate les chunks en contexte lisible pour le LLM.
    Respecte la limite de caractères (~4000 tokens).
    """
    blocs  = []
    total  = 0

    for i, chunk in enumerate(chunks):
        source = chunk.get("source_nom") or "Source inconnue"
        titre  = chunk.get("titre") or ""
        date   = (chunk.get("publie_le") or "")[:10]
        url    = chunk.get("url_original") or ""
        texte  = chunk.get("contenu") or ""

        bloc = (
            f"[{i+1}] {source} — {titre} ({date})\n"
            f"URL : {url}\n"
            f"{texte}"
        )

        if total + len(bloc) > max_chars:
            break

        blocs.append(bloc)
        total += len(bloc)

    return "\n\n---\n\n".join(blocs)
