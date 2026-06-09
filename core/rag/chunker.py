"""
core/rag/chunker.py — Découpage des articles en chunks
Stratégie : découpage récursif avec chevauchement
  - Taille cible  : 1600 caractères (~400 tokens)
  - Chevauchement : 200 caractères (~50 tokens)
  - Traitement incrémental — uniquement les articles non chunkés
  - Micro-batches pour éviter la surcharge mémoire
  - Filtre thématique IF : articles hors périmètre marqués et ignorés
"""
import os, sys, logging, unicodedata
sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
from core.database import get_db, new_id, now_iso

log = logging.getLogger(__name__)

CHUNK_SIZE    = 1600
CHUNK_OVERLAP = 200
MIN_CHUNK_LEN = 100
BATCH_SIZE    = 100   # articles traités par lot

# ── Filtre thématique ────────────────────────────────────────────────────────
# Mots-clés normalisés (sans accents, minuscules) associés à la finance / IF.
# Un article dont le titre + les 600 premiers caractères du contenu ne
# contiennent AUCUN de ces termes est marqué 'hors_perimetre' et ignoré
# lors de l'indexation FAISS.
_MOTS_CLES_IF: list[str] = [
    # Institutions / banques centrales
    "beac", "cemac", "diif", "bceao", "uemoa", "imf", "fmi",
    "banque mondiale", "world bank", "banque centrale", "central bank",
    "banque de france", "bank of", "bis ",
    # Inclusion / innovation financières
    "inclusion financ", "financial inclusion",
    "mobile money", "fintech", "microfinance", "microassurance",
    "bancarisation", "banque", "bancaire", "banking",
    "microcredit", "microcredit",
    # Opérations financières
    "credit", "epargne", "depot", "paiement", "payment",
    "transfert", "virement", "remittance", "monnaie", "currency",
    "investissement", "investment", "assurance", "insurance",
    "portefeuille", "wallet",
    # Finance numérique
    "digital finance", "finance numerique", "finance digitale",
    "innovation financ", "open banking", "blockchain", "cbdc",
    "monnaie electronique", "e-money",
    # Économie / régulation
    "taux d interet", "taux de change", "inflation",
    "economie", "economique", "fiscal", "monetaire", "macroeconom",
    "regulation", "reglementation", "supervision",
    # Géographie IF
    "afrique", "africa", "cameroun", "congo", "gabon",
    "tchad", "guinee equatoriale", "zone cemac",
    # Dimensions IF
    "education financiere", "litteratie financiere",
    "protection du consommateur",
]


def _norm(text: str) -> str:
    """Minuscules + suppression des diacritiques."""
    return (
        unicodedata.normalize("NFKD", text.lower())
        .encode("ascii", errors="ignore")
        .decode()
    )


def est_dans_perimetre(titre: str, contenu: str) -> bool:
    """
    Retourne True si l'article est lié à l'inclusion / innovation financières.
    Teste le titre et les 600 premiers caractères du contenu.
    """
    extrait = _norm((titre or "") + " " + (contenu or "")[:600])
    return any(kw in extrait for kw in _MOTS_CLES_IF)
# ────────────────────────────────────────────────────────────────────────────


def split_text(texte: str) -> list:
    """
    Découpe un texte en chunks avec chevauchement.
    Respecte les séparateurs naturels dans l'ordre de priorité.
    """
    if not texte or len(texte) < MIN_CHUNK_LEN:
        return []

    separateurs = ["\n\n", "\n", ". ", "? ", "! ", "; ", ", ", " "]
    chunks_result = []

    def _split(text, seps):
        if not text or len(text.strip()) < MIN_CHUNK_LEN:
            return
        if len(text) <= CHUNK_SIZE:
            chunks_result.append(text.strip())
            return
        if not seps:
            # Dernier recours : découpe brute
            for i in range(0, len(text), CHUNK_SIZE - CHUNK_OVERLAP):
                partie = text[i:i + CHUNK_SIZE].strip()
                if len(partie) >= MIN_CHUNK_LEN:
                    chunks_result.append(partie)
            return

        sep = seps[0]
        parties = text.split(sep)
        buffer = ""

        for partie in parties:
            candidat = (buffer + sep + partie) if buffer else partie
            if len(candidat) <= CHUNK_SIZE:
                buffer = candidat
            else:
                if len(buffer.strip()) >= MIN_CHUNK_LEN:
                    chunks_result.append(buffer.strip())
                    overlap = buffer[-CHUNK_OVERLAP:] if len(buffer) > CHUNK_OVERLAP else buffer
                    buffer = overlap + sep + partie
                else:
                    _split(partie, seps[1:])
                    buffer = partie

        if buffer and len(buffer.strip()) >= MIN_CHUNK_LEN:
            chunks_result.append(buffer.strip())

    _split(texte, separateurs)
    return chunks_result


def sauvegarder_chunks(chunks: list) -> int:
    """Insère les chunks en base. Retourne le nombre insérés."""
    if not chunks:
        return 0
    inseres = 0
    with get_db() as conn:
        for chunk in chunks:
            try:
                conn.execute("""
                    INSERT OR IGNORE INTO chunks
                        (id, article_id, document_id, contenu,
                         position, indexe_le, faiss_id)
                    VALUES
                        (:id, :article_id, :document_id, :contenu,
                         :position, :indexe_le, :faiss_id)
                """, chunk)
                inseres += 1
            except Exception as e:
                log.warning(f"Chunk non inséré : {e}")
    return inseres


def chunker_articles_nouveaux() -> dict:
    """
    Chunke uniquement les articles pas encore découpés.
    Traitement par micro-batches — scalable quelle que soit
    la taille de la base.
    Les articles hors périmètre IF sont marqués 'hors_perimetre'
    et exclus de l'indexation FAISS sans être supprimés.
    """
    stats = {"articles": 0, "chunks": 0, "ignores": 0, "hors_perimetre": 0}

    while True:
        # Prendre un micro-batch d'articles non chunkés et dans le périmètre
        with get_db() as conn:
            articles = conn.execute("""
                SELECT a.id, a.contenu, a.titre, a.langue
                FROM articles a
                WHERE a.contenu IS NOT NULL
                  AND a.contenu != ''
                  AND LENGTH(a.contenu) >= ?
                  AND a.qualite_contenu != 'hors_perimetre'
                  AND NOT EXISTS (
                      SELECT 1 FROM chunks c
                      WHERE c.article_id = a.id
                  )
                ORDER BY a.collecte_le DESC
                LIMIT ?
            """, (MIN_CHUNK_LEN, BATCH_SIZE)).fetchall()

        if not articles:
            break

        for art in articles:
            # Filtre thématique : ignorer les articles hors IF/finance
            if not est_dans_perimetre(art["titre"] or "", art["contenu"] or ""):
                with get_db() as conn:
                    conn.execute(
                        "UPDATE articles SET qualite_contenu = 'hors_perimetre' "
                        "WHERE id = ?",
                        (art["id"],)
                    )
                stats["hors_perimetre"] += 1
                log.info(
                    f"[CHUNKER] Hors périmètre : {(art['titre'] or '')[:70]!r}"
                )
                continue

            morceaux = split_text(art["contenu"])
            if not morceaux:
                stats["ignores"] += 1
                continue

            chunks = []
            for i, texte in enumerate(morceaux):
                chunks.append({
                    "id":          new_id(),
                    "article_id":  art["id"],
                    "document_id": None,
                    "contenu":     texte,
                    "position":    i,
                    "indexe_le":   None,
                    "faiss_id":    None,
                })

            n = sauvegarder_chunks(chunks)
            stats["chunks"]   += n
            stats["articles"] += 1

        log.info(
            f"[CHUNKER] Batch : {stats['articles']} articles, "
            f"{stats['chunks']} chunks, "
            f"{stats['hors_perimetre']} hors périmètre"
        )

    return stats


def chunker_document_nouveau(document_id: str, contenu: str) -> int:
    """Chunke un document uploadé. Retourne le nombre de chunks créés."""
    if not contenu:
        return 0
    morceaux = split_text(contenu)
    chunks = []
    for i, texte in enumerate(morceaux):
        chunks.append({
            "id":          new_id(),
            "article_id":  None,
            "document_id": document_id,
            "contenu":     texte,
            "position":    i,
            "indexe_le":   None,
            "faiss_id":    None,
        })
    return sauvegarder_chunks(chunks)


def get_stats_chunks() -> dict:
    with get_db() as conn:
        total    = conn.execute(
            "SELECT COUNT(*) FROM chunks").fetchone()[0]
        indexes  = conn.execute(
            "SELECT COUNT(*) FROM chunks WHERE faiss_id IS NOT NULL"
        ).fetchone()[0]
        articles_chunkés = conn.execute(
            "SELECT COUNT(DISTINCT article_id) FROM chunks "
            "WHERE article_id IS NOT NULL"
        ).fetchone()[0]
        articles_total = conn.execute(
            "SELECT COUNT(*) FROM articles WHERE contenu IS NOT NULL "
            "AND contenu != ''"
        ).fetchone()[0]
        hors_perimetre = conn.execute(
            "SELECT COUNT(*) FROM articles "
            "WHERE qualite_contenu = 'hors_perimetre'"
        ).fetchone()[0]
    return {
        "total":             total,
        "indexes":           indexes,
        "en_attente":        total - indexes,
        "articles_chunkés":  articles_chunkés,
        "articles_total":    articles_total,
        "articles_restants": articles_total - articles_chunkés,
        "hors_perimetre":    hors_perimetre,
    }
