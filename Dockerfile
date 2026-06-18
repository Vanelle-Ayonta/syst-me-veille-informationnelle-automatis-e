FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    # Cache modeles dans /app/models (copie dans l'image au build)
    HF_HOME=/app/models \
    HUGGINGFACE_HUB_CACHE=/app/models/hub \
    TRANSFORMERS_CACHE=/app/models/hub \
    SENTENCE_TRANSFORMERS_HOME=/app/models/hub \
    # Indique a config.py d'utiliser /data comme racine persistante
    HF_SPACE=true

WORKDIR /app

RUN apt-get update && apt-get install -y curl \
    && rm -rf /var/lib/apt/lists/* \
    # Utilisateur non-root requis par HuggingFace Spaces (UID 1000)
    && useradd -m -u 1000 appuser

# ── Dependances Python ───────────────────────────────────────────────────────
COPY requirements.txt .
# torch CPU depuis PyPI (pas de wheel local sur HF)
RUN pip install --no-cache-dir torch==2.3.1+cpu \
        --index-url https://download.pytorch.org/whl/cpu \
    && grep -vE "^torch" requirements.txt > /tmp/req_light.txt \
    && pip install --no-cache-dir --timeout 180 --retries 5 \
        -r /tmp/req_light.txt \
    && rm /tmp/req_light.txt

# ── Telechargement des modeles au build (evite le delai au 1er lancement) ───
RUN python - <<'PY'
from huggingface_hub import snapshot_download
snapshot_download("intfloat/multilingual-e5-base",
                  cache_dir="/app/models/hub",
                  ignore_patterns=["*.h5","*.ot","flax_*","tf_*"])
snapshot_download("cross-encoder/mmarco-mMiniLMv2-L12-H384-v1",
                  cache_dir="/app/models/hub",
                  ignore_patterns=["*.h5","*.ot","flax_*","tf_*"])
print("Modeles OK")
PY

# ── Code source ──────────────────────────────────────────────────────────────
COPY . .

# Dossier /data monte par HF Spaces (persistant entre redemarrages)
# Les sous-dossiers seront crees par entrypoint.sh au premier lancement
RUN chmod +x /app/entrypoint.sh \
    && mkdir -p /data/uploads /data/exports /data/backups \
    && chown -R appuser:appuser /app /data

USER appuser

EXPOSE 7860

HEALTHCHECK --interval=30s --timeout=10s --start-period=90s \
    CMD curl -f http://localhost:7860/_stcore/health || exit 1

ENTRYPOINT ["/app/entrypoint.sh"]
