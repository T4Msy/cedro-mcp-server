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

- Resolver a pauta de Saulo/Adriel registrada em `04-gap-analysis.md` (nomes de `roles`/`claims`
  reais, URL de produção do IAM, dono da cota por tier).
- Obter validação jurídica/comercial da nota **REQUIRES LEGAL/COMMERCIAL VALIDATION**
  (`03-commercial-entitlement.md`) antes de qualquer divulgação ampla.
- Deploy real em Render (ou equivalente), com `MCP_ALLOWED_HOSTS`/`MCP_ALLOWED_ORIGINS`
  configurados para o host de produção.

## Fase 4 — Consolidação de tools (opcional, produto)

Executar o refactor descrito em `07-tools-consolidation.md` (26 → ~15 tools) como mudança
deliberada e isolada, com seu próprio ciclo de revisão — não misturada às fases anteriores.

## Fora deste plano

- F2 (Market Data Socket / streaming) e demais produtos (Trading, Conta/Análise, Cadastro/
  Backoffice) — MCPs separados, "1 MCP por produto" (decisão já registrada em `Arquitetura do MCP
  (transporte, IAM, entitlements).md`), fora do escopo deste servidor.
