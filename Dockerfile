# Image unique : l'interface et l'API. Le worker Render réutilise cette image
# avec la commande `python -m app.worker`.
FROM node:22-alpine AS web
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim

WORKDIR /srv

RUN apt-get update && apt-get install -y --no-install-recommends gcc g++ && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt .
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
 && pip install --no-cache-dir -r requirements.txt \
 && python -m spacy download fr_core_news_md \
 && python -m spacy download en_core_web_md \
 && python -m spacy download de_core_news_md \
 && python -m spacy download es_core_news_md \
 && python -m spacy download it_core_news_md \
 && python -m spacy download nl_core_news_md \
 && python -m spacy download pt_core_news_md \
 && python -m spacy download xx_ent_wiki_sm \
 && python -m playwright install chromium --with-deps

COPY backend/app ./app
COPY --from=web /app/dist ./static

ENV STATIC_DIR=/srv/static \
    ARTIFACTS_DIR=/tmp/tacite-artifacts \
    HF_HOME=/tmp/hf \
    PYTHONUNBUFFERED=1

EXPOSE 8000
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
