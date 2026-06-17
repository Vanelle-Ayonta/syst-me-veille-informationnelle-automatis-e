FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    HF_HOME=/app/models \
    HUGGINGFACE_HUB_CACHE=/app/models/hub \
    TRANSFORMERS_CACHE=/app/models/hub \
    SENTENCE_TRANSFORMERS_HOME=/app/models/hub

WORKDIR /app

RUN apt-get update && apt-get install -y curl \
    && rm -rf /var/lib/apt/lists/*

# torch Linux CPU — wheel local (evite 700 MB de telechargement)
COPY local_packages/wheels/torch*.whl /tmp/
RUN pip install --no-cache-dir /tmp/torch*.whl \
    && rm /tmp/torch*.whl

# sentence-transformers et le reste des dependances
COPY requirements.txt .
RUN grep -vE "^torch" requirements.txt > /tmp/req_light.txt \
    && pip install --no-cache-dir --timeout 120 --retries 5 -r /tmp/req_light.txt \
    && rm /tmp/req_light.txt

# Modeles HuggingFace — copies depuis le cache local (pas de reseau au build)
COPY model_cache/models--intfloat--multilingual-e5-base \
     /app/models/hub/models--intfloat--multilingual-e5-base

COPY model_cache/models--cross-encoder--mmarco-mMiniLMv2-L12-H384-v1 \
     /app/models/hub/models--cross-encoder--mmarco-mMiniLMv2-L12-H384-v1

# Code source (en dernier pour ne pas invalider les layers lourds)
COPY . .

RUN mkdir -p data/uploads data/exports data/backups

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=10s \
    --start-period=60s \
    CMD curl -f http://localhost:8501/_stcore/health \
    || exit 1

CMD ["python", "-m", "streamlit", "run", "app.py", \
     "--server.port=8501", \
     "--server.address=0.0.0.0", \
     "--server.headless=true"]
