"""
core/rag/pipeline.py — Orchestrateur du pipeline RAG
Point d'entrée unique pour chunking + indexation + recherche.
"""
import logging
log = logging.getLogger(__name__)


def run_pipeline() -> dict:
    """
    Lance le pipeline incrémental complet :
    1. Chunking des articles non encore découpés
    2. Indexation FAISS des chunks non encore indexés
    Ne retraite jamais ce qui est déjà fait.
    """
    from core.rag.chunker import chunker_articles_nouveaux
    from core.rag.indexer import indexer_chunks_nouveaux

    log.info("\n[PIPELINE] Étape 1/2 — Chunking...")
    s_chunk = chunker_articles_nouveaux()
    log.info(f"[PIPELINE] {s_chunk['articles']} articles → "
             f"{s_chunk['chunks']} chunks créés")

    log.info("\n[PIPELINE] Étape 2/2 — Indexation FAISS...")
    s_index = indexer_chunks_nouveaux()
    log.info(f"[PIPELINE] {s_index['indexés']} chunks indexés | "
             f"Total : {s_index['total_index']} vecteurs")

    return {**s_chunk, **s_index}


def search(query: str,
           top_k: int = 8,
           langue: str = None) -> list:
    """Recherche sémantique simple."""
    from core.rag.retriever import rechercher
    return rechercher(query, top_k=top_k,
                      filtre_langue=langue)


def search_with_context(query: str,
                        top_k: int = 8,
                        langue: str = None) -> tuple:
    """Recherche + contexte formaté pour le LLM."""
    from core.rag.retriever import rechercher, formater_contexte
    chunks   = rechercher(query, top_k=top_k,
                          filtre_langue=langue)
    contexte = formater_contexte(chunks)
    return chunks, contexte


def get_stats() -> dict:
    """État complet du pipeline RAG."""
    from core.rag.chunker import get_stats_chunks
    from core.rag.indexer import get_stats_index
    return {
        "chunks": get_stats_chunks(),
        "index":  get_stats_index(),
    }
