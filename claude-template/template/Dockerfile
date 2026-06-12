# Production / Cloud Run image — ONE container per service.
# Local dev keeps using the per-service Dockerfiles via docker-compose;
# this root Dockerfile exists so a single `gcloud run deploy --source .`
# builds and ships the whole app. See docs/deploy-cloudrun.md.

# --frontend-start (removed by `scaffold.py new --no-frontend`)
# The Vite frontend is compiled here and served by FastAPI from
# `static/`, since Cloud Run runs one container per service.
FROM node:20-alpine AS frontend-build
WORKDIR /fe
COPY frontend/package.json ./
RUN npm install
COPY frontend/ .
RUN npm run build
# --frontend-end

FROM python:3.12-slim
WORKDIR /code

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# git + Claude Code CLI for headless workflows (see app/headless.py).
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl git ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && curl -fsSL https://claude.ai/install.sh | bash \
    && git config --global --add safe.directory '*'
ENV PATH="/root/.local/bin:${PATH}"

COPY backend/app ./app
# --frontend-start
COPY --from=frontend-build /fe/dist ./static
# --frontend-end

# Cloud Run injects PORT (8080 by default); shell form so it expands.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
