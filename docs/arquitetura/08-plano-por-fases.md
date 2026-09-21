# Plano por fases

## Fase 0 — Saneamento (esta entrega)

Escopo fechado nesta rodada, sem features novas:

- [x] Unificar as duas cópias do servidor sob git; `Market Data/mcp-server/` removida;
      `render.yaml`/`DEPLOY-RENDER.md` apontando para a canônica.
- [x] Fechar o vazamento do vault — `CEDRO_DOCS_PATH` aponta para a skill pública `market-data-rest`.
- [x] Corrigir o bug de subpasta em `cedro-docs://note/{path}` (token/slug).
- [x] `MCP_TRANSPORT` rejeita `"sse"` em vez de tratá-lo como Streamable HTTP em silêncio.
- [x] Container roda como usuário não-root.
- [x] `md_get_candles_last(count)` com teto; encoding em `news_search`/`md_get_quote`.
- [x] README/docs com contagem de testes atualizada (68) e modelo de credencial atualizado.
- [x] Este dossiê de arquitetura (`docs/arquitetura/`).

Critério de pronto: `pytest`/`ruff` verdes, teste de vazamento do vault passando, `git log`
mostrando a canônica versionada.

## Fase 1 — Credencial por cliente (Alternativa A)

Implementar as consequências obrigatórias registradas em `06-credential-transport.md`:
`PerUserCredentialProvider` real, sessão `JSESSIONID` cacheada por hash de credencial com store
compartilhado, limitador de `SignIn` por login, revisão de `stateless_http`. Depende de decisão
explícita sobre o store de sessão compartilhado (Redis ou equivalente) se o deploy for multi-réplica
desde o início.

## Fase 2 — Validação contra a API real

`scripts/smoke_live.py` contra credencial de sandbox/homologação real. Bloqueado por: obter uma
credencial de teste da Cedro. É a pendência mais antiga do projeto e deve ser o próximo passo depois
da Fase 1, antes de qualquer deploy de produção com clientes reais.

## Fase 3 — Deploy e alinhamento comercial

- [x] **Deploy real feito** (21/09) — Hostinger VPS + Cloudflare quick tunnel, com
  `MCP_WEB_LOGIN=true` (login pelo navegador) em vez de IAM. Ver
  `09-deploy-hostinger-cloudflare.md`. Uso pessoal/demo, não produção multi-cliente pública ainda.
- IAM (`roles`/`claims` reais, URL de produção) e emissão de API key: **parados por decisão do
  usuário** — "vamos continuar da forma que está sendo feita" até ele pedir pra retomar.
- Redistribuição/display-vs-non-display: **fechado**, não se aplica (decisão do usuário, ver
  `03-commercial-entitlement.md`) — não é mais bloqueio.
- Cota por tier: sem dono, sem prazo — fica registrado, não é urgente.
- Pendente: confirmar com a comercial da Cedro se a conta de teste precisa do flag/plano
  "profissional" para os endpoints de ranking (achado ao vivo, ver `04-gap-analysis.md`).

## Fase 4 — Consolidação de tools (opcional, produto)

Executar o refactor descrito em `07-tools-consolidation.md` (26 → ~15 tools) como mudança
deliberada e isolada, com seu próprio ciclo de revisão — não misturada às fases anteriores.

## Fora deste plano

- F2 (Market Data Socket / streaming) e demais produtos (Trading, Conta/Análise, Cadastro/
  Backoffice) — MCPs separados, "1 MCP por produto" (decisão já registrada em `Arquitetura do MCP
  (transporte, IAM, entitlements).md`), fora do escopo deste servidor.
