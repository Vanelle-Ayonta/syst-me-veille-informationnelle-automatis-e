"""
core/document_processor.py — Traitement des documents uploadés
Extraction de texte depuis PDF, DOCX, TXT.
Pipeline complet : écriture disque → extraction texte → chunking → indexation FAISS.
"""
import os, sys, logging
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.database import get_db, new_id, now_iso

log = logging.getLogger(__name__)

try:
    import fitz  # PyMuPDF
    PYMUPDF_OK = True
except ImportError:
    PYMUPDF_OK = False

try:
    from docx import Document as DocxDocument
    DOCX_OK = True
except ImportError:
    DOCX_OK = False


def extraire_texte(chemin: str, type_doc: str) -> str:
    """Extrait le texte brut d'un fichier selon son type."""
    try:
        if type_doc == "pdf" and PYMUPDF_OK:
            doc  = fitz.open(chemin)
            return "\n".join(p.get_text() for p in doc)
        elif type_doc == "docx" and DOCX_OK:
            doc  = DocxDocument(chemin)
            return "\n".join(p.text for p in doc.paragraphs)
        elif type_doc == "txt":
            with open(chemin, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()
    except Exception as e:
        print(f"[ERREUR extraction] {chemin} : {e}")
    return ""


def detecter_type(nom_fichier: str) -> str:
    ext = nom_fichier.rsplit(".", 1)[-1].lower()
    mapping = {"pdf": "pdf", "docx": "docx", "doc": "docx", "txt": "txt"}
    return mapping.get(ext, "autre")


def sauvegarder_document(
    nom_fichier: str,
    contenu_bytes: bytes,
    description: str,
    uploade_par: str,
    uploads_dir: str
) -> dict:
    """
    Pipeline complet pour un document uploadé :
    1. Écriture du fichier sur disque
    2. Insertion des métadonnées en SQLite (indexe=0)
    3. Extraction du texte (PyMuPDF / python-docx / txt)
    4. Chunking et sauvegarde des chunks en SQLite
    5. Indexation FAISS des nouveaux chunks
    6. Mise à jour indexe=1 dans la table documents

    Retourne {"success": bool, "doc_id": str, "message": str,
              "nb_chunks": int}
    """
    os.makedirs(uploads_dir, exist_ok=True)
    doc_id    = new_id()
    type_doc  = detecter_type(nom_fichier)
    safe_name = f"{doc_id}_{nom_fichier}"
    chemin    = os.path.join(uploads_dir, safe_name)

    # ── 1. Écriture disque ───────────────────────────────────────────────────
    try:
        with open(chemin, "wb") as f:
            f.write(contenu_bytes)
    except Exception as e:
        return {"success": False, "doc_id": None, "nb_chunks": 0,
                "message": f"Erreur écriture : {e}"}

    # ── 2. Enregistrement métadonnées (indexe=0 en attente) ─────────────────
    with get_db() as conn:
        conn.execute("""
            INSERT INTO documents
                (id, nom_fichier, chemin_stockage, type_doc,
                 description, uploade_par, uploade_le, indexe)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0)
        """, (doc_id, nom_fichier, chemin, type_doc,
              description, uploade_par, now_iso()))

    if type_doc == "autre":
        return {"success": True, "doc_id": doc_id, "nb_chunks": 0,
                "message": (f"Document «