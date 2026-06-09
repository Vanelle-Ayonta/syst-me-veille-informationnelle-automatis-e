"""
core/rag/embedder.py — Génération des embeddings
Modèle : intfloat/multilingual-e5-base
  - Multilingue FR/EN optimisé
  - Fenêtre 512 tokens
  - Lazy loading — chargé seulement quand nécessaire
  - Prefixes query/passage requis par le modèle e5
"""
import os, sys, logging, threading
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
from config import EMBEDDING_MODEL

log = logging.getLogger(__name__)
_model = None
_dim   = None
_lock  = threading.Lock()   # protège le chargement concurrent (threads anyio)


def get_model():
    """
    Singleton lazy thread-safe — jamais de st.* ici.
    pydantic-ai exécute les outils sync dans un thread pool anyio ;
    tout appel Streamlit depuis ce contexte lève NoSessionContext.
    """
    global _model, _dim
    if _model is None:
        with _lock:
            if _model is None:   # double-checked locking
                from sentence_transformers import SentenceTransformer
                log.info(f"[EMBEDDER] Chargement {EMBEDDING_MODEL}...")
                m = SentenceTransformer(
                    EMBEDDING_MODEL,
                    cache_folder=os.environ.get("SENTENCE_TRANSFORMERS_HOME"),
                )
                _dim = (
                    m.get_embedding_dimension()
                    if hasattr(m, "get_embedding_dimension")
                    else m.get_sentence_embedding_dimension()
                )
                log.info(f"[EMBEDDER] Modèle chargé — dim={_dim}")
                _model = m   # assignation atomique en dernier
    return _model


def get_dim() -> int:
    """Retourne la dimension sans charger le modèle si déjà connu."""
    global _dim
    if _dim is None:
        get_model()
    return _dim


def embed_texts(textes: list,
                batch_size: int = 32,
                is_query: bool = False) -> np.ndarray:
    """
    Génère les embeddings.
    Le modèle e5 requiert des préfixes :
      - 'query: '   pour les requêtes utilisateur
      - 'passage: ' pour les documents à indexer
    """
    model = get_model()
    prefix = "query: " if is_query else "passage: "
    prefixed = [prefix + t for t in textes]
    return model.encode(
        prefixed,
        batch_size=batch_size,
        show_progress_bar=len(textes) > 100,
        normalize_embeddings=True,
        convert_to_numpy=True,
    )


def embed_query(query: str) -> np.ndarray:
    return embed_texts([query], is_query=True)[0]


def embed_chunks_list(textes: list,
                      batch_size: int = 32) -> np.ndarray:
    return embed_texts(textes, batch_size=batch_size, is_query=False)
