# Build reproduzível do cedro-mcp-server. Este container serve o transporte Streamable HTTP
# (padrão de produção) — para stdio local, use o venv diretamente (ver README).
#
# IMPORTANTE: .env NÃO vai pra dentro da imagem (ver .dockerignore). Credenciais e config de
# auth entram em runtime via `docker run -e VAR=valor ...` ou `env_file` no compose — nunca
# via COPY de um .env real pra dentro do build.

FROM python:3.11-slim AS builder

WORKDIR /build
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir --prefix=/install ".[redis]"

FROM python:3.11-slim AS runtime

RUN groupadd --system cedro && useradd --system --gid cedro --no-create-home cedro

WORKDIR /app
COPY --from=builder /install /usr/local
COPY src ./src
RUN chown -R cedro:cedro /app

ENV MCP_TRANSPORT=streamable-http \
    MCP_HOST=0.0.0.0 \
    MCP_PORT=8000 \
    PYTHONUNBUFFERED=1

# A documentação servida por `cedro-docs://` (CEDRO_DOCS_PATH) fica FORA da imagem por padrão —
# monte como volume em runtime (ex.: `-v /caminho/local/market-data-rest:/docs -e
# CEDRO_DOCS_PATH=/docs`) apontando para a skill pública `market-data-rest`, NUNCA para o vault
# interno da Cedro (ver docs/arquitetura/ — vazamento de roadmap/comercial/backoffice).

USER cedro

EXPOSE 8000

# /health responde 200 {"status":"ok"} (503 se o Redis configurado estiver fora). Sem curl na
# imagem slim — usa o próprio Python.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"MCP_PORT\", \"8000\")}/health', timeout=4)" || exit 1

ENTRYPOINT ["cedro-mcp"]
