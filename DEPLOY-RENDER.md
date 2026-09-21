# Deploy do MCP Market Data no Render (free tier)

> Este arquivo substitui `Market Data/DEPLOY-RENDER.md` — aquela pasta continha uma cópia mais
> antiga do servidor (`Market Data/mcp-server/`), sem `resources.py` corrigido e sem as decisões
> registradas em `docs/arquitetura/`. Este repositório (`cedro-mcp-server/`) é o canônico.

O **MCP Server de Market Data** expõe o contrato da API (26 tools + docs) por **HTTP**
(Streamable HTTP), protegido por **IAM ou API key**.

> ⚠️ **Trade-off do free tier do Render:** o serviço **dorme após 15 min sem requisições** e leva
> ~30-60s pra acordar na próxima chamada.

## Pré-requisitos

- Este repositório (`cedro-mcp-server/`) precisa estar num repositório Git conectado ao Render
  (GitHub/GitLab) — o Render faz deploy a partir de um repo, não de um diretório local.
- `Dockerfile` e `render.yaml` já estão na raiz deste repo (Blueprint).
- **Diferente do deploy antigo**: o build context deste Dockerfile é só este repo — a
  documentação servida por `cedro-docs://` (skill pública `market-data-rest`) **não** é
  empacotada na imagem por padrão. Para servi-la em produção, vendorizar o conteúdo da skill
  dentro deste repo (ex. `docs/client-skill/`) e apontar `CEDRO_DOCS_PATH`, ou montar como
  volume. Sem isso configurado, os resources `cedro-docs://` só retornam vazio — nunca vazam o
  vault interno, que é a garantia que importa (ver `docs/arquitetura/02-security-model.md`).

## Passo a passo

1. Suba este repositório (`cedro-mcp-server/`) para o GitHub.
2. **render.com** → *New* → *Blueprint* → conecte o repositório → o Render lê o `render.yaml`
   automaticamente e propõe o serviço `cedro-mcp-market-data` (plano `free`, Docker).
3. Nas variáveis marcadas `sync: false` no `render.yaml`, o Render pede o valor no próprio fluxo:
   - `CEDRO_USER` / `CEDRO_PASS` — apenas para fallback de dev; produção usa credencial do
     cliente por requisição (ver `docs/arquitetura/06-credential-transport.md`).
   - `CEDRO_NEWS_CLIENT_ID` / `CEDRO_NEWS_CLIENT_SECRET` — auth do módulo de notícias (opcional).
   - `CEDRO_API_KEYS=k_algumacoisa:cedro-front-backend:marketdata:read|marketdata:news` — gere
     uma chave aleatória forte (ex.: `openssl rand -hex 24`).
   - `MCP_RESOURCE_URL` — deixe em branco por ora; preenche no passo 5.
   - `CEDRO_DOCS_PATH` — deixe em branco se não for vendorizar a skill nesta rodada.
4. Deploy. O Render gera uma URL pública tipo `https://cedro-mcp-market-data.onrender.com`.
5. Volte em **Environment** e preencha `MCP_RESOURCE_URL=https://SEU-SERVICO.onrender.com/mcp`.
   Salvar reinicia o deploy automaticamente.
6. Confira a saúde: `https://SEU-SERVICO.onrender.com/health` → `{"status":"ok"}`.

## Testar a auth (depois do deploy)

```bash
# sem token — espera 401
curl -i -X POST https://SEU-SERVICO.onrender.com/mcp \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","method":"tools/list","id":1}'

# com a API key — espera 200 e a lista de tools
curl -i -X POST https://SEU-SERVICO.onrender.com/mcp \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -H "Authorization: Bearer <sua CEDRO_API_KEYS>" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl","version":"1"}}}'
```

## Notas importantes

- **`CEDRO_IAM_ISSUER` não precisa ser um IAM funcional agora** — já vem preenchido com um valor
  placeholder no `render.yaml`. Sem `CEDRO_IAM_JWKS_URL`, a validação de fato é só via API key.
- **`MCP_ALLOWED_HOSTS`:** setar para o host público real gerado pelo Render, para religar a
  proteção anti-DNS-rebinding (o FastMCP só liga sozinho em host local — ver
  `docs/arquitetura/02-security-model.md`).
- **Cold start ~30-60s** após 15 min ocioso — planos pagos do Render removem o sleep.
- **Segredo `CEDRO_API_KEYS` nunca vai para o client.**
- **Validação contra a API real** (`scripts/smoke_live.py`) não faz parte deste passo — é a
  próxima fase depois deste deploy (ver `docs/arquitetura/08-plano-por-fases.md`).
