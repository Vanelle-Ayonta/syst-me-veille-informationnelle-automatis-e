#!/bin/bash
# entrypoint.sh — Initialisation au démarrage du conteneur HF Spaces
set -e

DATA_DIR="${DATA_DIR:-/data}"

# ── 1. Créer les dossiers persistants si absents ────────────────────────────
mkdir -p "$DATA_DIR/uploads" "$DATA_DIR/exports" "$DATA_DIR/backups"

# ── 2. Initialiser / mettre à jour la base de données ───────────────────────
# init_db.py utilise CREATE TABLE IF NOT EXISTS et INSERT OR IGNORE :
# il est safe à relancer à chaque démarrage — crée la base si absente,
# et ajoute les sources manquantes si la base existe déjà.
DB_PATH="${DB_PATH:-$DATA_DIR/veille_diif.db}"
echo "[INIT] Initialisation/mise à jour de la base de données..."
DB_PATH="$DB_PATH" python init_db.py
echo "[INIT] Base de données prête : $DB_PATH"

# ── 3. Vérifier l'index FAISS ────────────────────────────────────────────────
FAISS_PATH="${FAISS_INDEX_PATH:-$DATA_DIR/faiss_index}"
if [ ! -f "${FAISS_PATH}.bin" ]; then
    echo "[INIT] Index FAISS absent — sera créé au premier pipeline RAG."
else
    echo "[INIT] Index FAISS existant : ${FAISS_PATH}.bin"
fi

# ── 4. Lancer l'application Streamlit ────────────────────────────────────────
echo "[INIT] Démarrage de l'application sur le port 7860..."
exec python -m streamlit run app.py \
    --server.port=7860 \
    --server.address=0.0.0.0 \
    --server.headless=true \
    --server.enableCORS=false \
    --server.enableXsrfProtection=false
