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
- [x] README/docs com contagem de testes atualizada (139) e modelo de credencial atualizado.
- [x] Este dossiê de arquitetura (`docs/arquitetura/`).

Critério de pronto: `pytest`/`ruff` verdes, teste de vazamento do vault passando, `git log`
mostrando a canônica versionada.

## Fase 1 — Trading (concluída)

- [x] Cliente OMS, handshake `brokerServiceLogin`, leitura de ordens e ações reais atrás do gate
  `preview → confirm` de uso único.
- [x] Login pelo navegador aceita credenciais de Trading como produto opcional e separado.
- [ ] Validação contra ambiente real de homologação antes de liberar `trading_confirm` para uso real
  (ver `10-trading-auth.md`).

## Fase 2 — Market Data streaming (implementação concluída; validação real pendente)

- [x] Cliente Socket Crystal TCP, com handshake sob demanda e cache de cotação, livro agregado
  e fita por ativo.
- [x] Cinco tools de leitura (`stream_get_quote`, `stream_get_book`, `stream_get_tape`,
  `stream_unsubscribe`, `stream_status`) protegidas por `marketdata:stream`.
- [x] Uma conexão por hash de credencial Socket dentro do processo; `MDC 1`, failover com backoff
  mínimo de 3 segundos e sem abrir Socket só para consultar status.
- [x] Login web aceita uma conta Socket Crystal sem exigir REST; software key opcional no handshake.
- [ ] Gate real: validar handshake TCP, framing, `T:` incremental, `Z:` e `V:` com credencial de
  homologação.
- [ ] Deploy de streaming: exatamente uma réplica por credencial Socket. Para escalar, o conector e
  o lock precisam ser compartilhados antes de subir mais de um processo.

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

- Conta/Análise e Cadastro/Backoffice seguem como MCPs separados; o isolamento por produto/contrato
  continua sendo a arquitetura adotada.
