# ── Stage 1: build the React/TypeScript client ────────────────────────────────
FROM node:20-slim AS client-builder

WORKDIR /build

# Install deps (layer-cached unless lock file changes)
COPY package.json package-lock.json ./
RUN npm ci

# Copy build config and source
COPY tsconfig.json tsconfig.app.json tsconfig.node.json ./
COPY vite.config.ts tailwind.config.js postcss.config.js components.json ./
COPY client/ ./client/

RUN npm run build
# Output lands in /build/client/dist/

# ── Stage 2: Python runtime ────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

WORKDIR /app

# Convert Pipfile.lock → requirements.txt, install, then drop pipenv
COPY Pipfile Pipfile.lock ./
RUN pip install --no-cache-dir pipenv \
    && pipenv requirements > /tmp/requirements.txt \
    && pip install --no-cache-dir -r /tmp/requirements.txt \
    && pip uninstall -y pipenv \
    && rm -f Pipfile Pipfile.lock /tmp/requirements.txt

# Copy application source and alembic config
COPY server/ ./server/
COPY alembic.ini ./

# Copy compiled frontend from builder
COPY --from=client-builder /build/client/dist ./client/dist

# Persistent data directory (mount a volume here for the SQLite file)
RUN mkdir -p /app/data

EXPOSE 8000

# Run migrations then start the server
CMD ["sh", "-c", "alembic upgrade head && uvicorn server.src.main:app --host 0.0.0.0 --port 8000"]
