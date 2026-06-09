"""
core/document_processor.py — Traitement des documents uploadés
Extraction de texte depuis PDF, DOCX, TXT.
"""
import os, sys, uuid, shutil
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.database import get_db, new_id, now_iso

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
    Sauvegarde un document uploadé sur disque et en base.
    Retourne {"success": bool, "doc_id": str, "message": str}
    """
    os.makedirs(uploads_dir, exist_ok=True)
    doc_id    = new_id()
    type_doc  = detecter_type(nom_fichier)
    safe_name = f"{doc_id}_{nom_fichier}"
    chemin    = os.path.join(uploads_dir, safe_name)

    try:
        with open(chemin, "wb") as f:
            f.write(contenu_bytes)
    except Exception as e:
        return {"success": False, "doc_id": None, "message": f"Erreur écriture : {e}"}

    with get_db() as conn:
        conn.execute("""
            INSERT INTO documents
                (id, nom_fichier, chemin_stockage, type_doc,
                 description, uploade_par, uploade_le, indexe)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0)
        """, (doc_id, nom_fichier, chemin, type_doc,
              description, uploade_par, now_iso()))

    return {"success": True, "doc_id": doc_id,
            "message": f"Document « {nom_fichier} » enregistré."}


def get_all_documents():
    with get_db() as conn:
        rows = conn.execute("""
            SELECT d.*, u.nom as uploade_par_nom
            FROM documents d
            LEFT JOIN utilisateurs u ON d.uploade_par = u.id
            ORDER BY d.uploade_le DESC
        """).fetchall()
        return [dict(r) for r in rows]


def delete_document(doc_id: str) -> bool:
    with get_db() as conn:
        row = conn.execute(
            "SELECT chemin_stockage FROM documents WHERE id = ?", (doc_id,)
        ).fetchone()
        if not row:
            return False
        chemin = row["chemin_stockage"]
        conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
    try:
        if os.path.exists(chemin):
            os.remove(chemin)
    except Exception:
        pass
    return True
