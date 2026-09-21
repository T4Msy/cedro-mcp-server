# Cedro MCP Server — rumo ao "Cedro Connect IA"

Servidor **MCP** que expõe as APIs da Cedro como *tools* para IAs. Cobre Market Data REST, streaming
via **Socket Crystal (TCP/Telnet, porta 81)** e **Trading** (envio/edição/cancelamento de ordem, sempre atrás de
confirmação humana em duas etapas). O nome e
a instrução do servidor ainda dizem "cedro-market-data" — o rename pra "Cedro Connect IA" é a
última etapa do roadmap (`docs/arquitetura/08-plano-por-fases.md`, Fase 4), não afeta
funcionalidade.

> **Status:** construído e testado com **mocks/fixtures** (139 testes). Market Data REST está em
> produção pessoal (deploy real, ver `docs/arquitetura/09-deploy-hostinger-cloudflare.md`).
> Trading tem cobertura de teste completa mas **nunca rodou contra a API real** — ver
> `docs/arquitetura/10-trading-auth.md` antes de usar `trading_confirm` com dinheiro de verdade.
> Streaming ainda precisa de uma credencial Socket Crystal de homologação para validação real antes
> de ser ligado no deploy. Os endpoints documentados são `crystalhomologacao.cedrotech.com:81` e,
> em produção, `datafeed1.cedrotech.com:81` com `datafeed2.cedrotech.com:81` como failover.
> Arquitetura e decisões comerciais documentadas em `docs/arquitetura/`.

## Arquitetura

| Camada | Decisão |
|---|---|
| Modelo | **1 MCP por produto** (isolamento por contrato/plano) |
| Transporte | **Streamable HTTP** (`/mcp`) — cliente só precisa de URL + token. `stdio` disponível p/ dev |
| Auth do chamador | **IAM da Cedro** (Identity Server, JWT) **ou API key** (automação) |
| Autorização | **Entitlements por escopo**: o cliente só *vê* e só *executa* as tools do plano contratado |
| Credencial downstream | `CredentialProvider` **plugável** — decidido: credencial do **próprio cliente**, enviada por requisição (`PerUserCredentialProvider`); `ServiceAccountCredentialProvider` fica só para dev local |
| Rate limit | Middleware ASGI por token |

> ⚠️ **Transporte:** a reunião decidiu "HTTP via SSE". Implementamos **Streamable HTTP** porque o SSE
> é o transporte **legado** do spec MCP — atende os mesmos requisitos (URL + token, sem instalar nada,
> rate limit) sem nascer obsoleto. **Pendente de alinhamento com o Adriel.**

### Escopos

| Escopo | Libera |
|---|---|
| `marketdata:read` | 17 tools: cotações, candles, book, negócios, rankings, altas/baixas |
| `marketdata:news` | 9 tools de notícias |
| `marketdata:stream` | 5 tools de streaming: cotação, livro, fita, cancelamento e status |

`marketdata:read` é exigido para conectar ao servidor. Nomes **provisórios** até a Cedro confirmar os
`roles`/`claims` reais do IAM — o único ponto de verdade é `src/cedro_mcp/auth/scopes.py`.

## Tools

### Market Data REST (26, read-only)

| Grupo | Tools |
|---|---|
| Cotações & ativos | `md_get_quote`, `md_get_quote_info`, `md_list_markets`, `md_list_indices`, `md_get_index_assets`, `md_get_company_quotes`, `md_list_options` |
| Candles | `md_get_candles_last`, `md_get_candles_range` |
| Book (DOM) | `md_get_book` (`full`/`aggregated`/`mini`) |
| Negócios (fita) | `md_get_trades_range`, `md_get_trades_date` |
| Rankings/Volume/Movers | `md_get_player_ranking`, `md_get_cross_ranking`, `md_get_volume_at_price`, `md_get_gainers`, `md_get_losers` |
| Notícias | `news_get_last`, `news_get_by_code`, `news_by_date`, `news_by_agency`, `news_relevant_facts`, `news_relevant_facts_by_quote`, `news_list_agencies`, `news_search`, `news_relevant_facts_by_agency` |

A documentação pública da skill `market-data-rest` também é exposta como **resources**
`cedro-docs://index` e `cedro-docs://note/{token}` (nunca o vault interno).

### Market Data streaming (5, read-only)

| Tool | Comportamento |
|---|---|
| `stream_get_quote` | Assina a cotação e devolve o último snapshot (último, bid e ask) |
| `stream_get_book` | Assina o livro agregado via `SAB`; `A` = compra e `V` = venda |
| `stream_get_tape` | Assina a fita e devolve os últimos N negócios do cache |
| `stream_unsubscribe` | Cancela as assinaturas do ativo e limpa seus snapshots locais |
| `stream_status` | Mostra conexão e ativos assinados, sem abrir login só para consultar status |

As tools exigem `marketdata:stream` e uma credencial **Socket Crystal** (separada de REST). Configure
`CEDRO_CRYSTAL_HOST` (host único ou lista separada por vírgulas), `CEDRO_CRYSTAL_PORT=81`,
`CEDRO_CRYSTAL_USER` e `CEDRO_CRYSTAL_PASSWORD`. O processo mantém uma conexão por credencial,
usa `MDC 1` antes de `SQT`, e aplica backoff mínimo de 3 segundos no failover.

### Trading (6 — leitura + ação real com confirmação)

| Grupo | Tools |
|---|---|
| Consulta (leitura) | `trading_list_orders_today`, `trading_get_order_history` |
| Ação real — **preview → confirm** | `trading_preview_order` (8 tipos, incl. condicionais nativas Start/Stop/StopConditional/StopMoving/StopOCO/StopSimult), `trading_preview_cancel_order`, `trading_preview_edit_order`, `trading_confirm` |

Toda tool de escrita monta e valida a ordem sem enviar nada (`trading_preview_*`), devolve um
resumo + `confirmation_token`, e só executa depois de `trading_confirm(token)` — nunca dispara
sozinha a partir de um evento. Token de uso único, expira em ~2 min. Credencial de Trading é
**separada** da Market Data (seção opcional no formulário `/cedro-login`, ou
`CEDRO_TRADING_USER`/`CEDRO_TRADING_PASS` em dev). Ver `docs/arquitetura/10-trading-auth.md`.

## Instalação

```powershell
cd cedro-mcp-server
python -m venv .venv
.\.venv\Scripts\Activate.ps1      # Git Bash: source .venv/Scripts/activate
pip install -e ".[dev]"
copy .env.example .env
```

## Rodar

```powershell
python -m cedro_mcp.server        # Streamable HTTP em http://127.0.0.1:8000/mcp
```

Cliente MCP conecta com a URL + `Authorization: Bearer <token-ou-api-key>`.

Para desenvolvimento local sem auth:

```powershell
$env:MCP_TRANSPORT="stdio"; python -m cedro_mcp.server
mcp dev src/cedro_mcp/server.py   # Inspector (requer Node/npx)
```

> Sem `CEDRO_IAM_ISSUER` + `MCP_RESOURCE_URL`, o servidor sobe **sem autenticação** e expõe todas as
> tools. Use apenas em dev local.

### Login pelo navegador (`MCP_WEB_LOGIN=true`)

Alternativa ao IAM/API key acima, pra quando não há IAM da Cedro configurado ainda: com
`MCP_WEB_LOGIN=true`, o próprio MCP vira a autoridade OAuth. O cliente MCP (Claude Desktop,
claude.ai, etc.) abre uma aba para informar as credenciais dos produtos desejados: REST, Streaming
Socket e/ou Trading. REST e Trading são confirmados no login; Socket só faz handshake quando uma
tool `stream_*` for solicitada, prevenindo uma conexão extra. O servidor devolve um token — sem
copiar/colar nada, sem senha em arquivo de config. Implementação em `src/cedro_mcp/web_login.py`;
decisão registrada em
`docs/arquitetura/06-credential-transport.md`.

```powershell
$env:MCP_WEB_LOGIN="true"; python -m cedro_mcp.server
```

> ⚠️ A credencial fica em **memória do processo** enquanto o token for válido (30 dias, sem
> refresh — expira, reloga pela aba). Nunca em disco, nunca persistida — mas é mais exposição do
> que o header por requisição puro. Reiniciar o processo desloga todo mundo.

## ⚠️ Notas de produção

1. **Anti-DNS-rebinding:** o FastMCP só liga essa proteção sozinho quando o host é
   `127.0.0.1`/`localhost`. Servindo em `0.0.0.0` atrás de um LB ela fica **desligada** — preencha
   `MCP_ALLOWED_HOSTS` (ex.: `mcp.cedrotech.com:*`).
2. **Rate limit em memória, por processo.** Com N réplicas, o limite efetivo é `N × MCP_RATE_LIMIT`.
   Para limite global, trocar por um backend compartilhado (Redis).
3. **Credencial downstream:** decidido — credencial **do próprio cliente** (o `md_xxxx` que ele já
   contratou), enviada por requisição. Consequências obrigatórias: sessão `JSESSIONID` cacheada por
   **hash** da credencial (nunca a credencial em si), store compartilhado entre réplicas, limitador
   de `SignIn` por login (a conta Market Data tolera pouco login/dia), e credencial fora de
   log/trace/erro/resposta de tool. Ver `docs/arquitetura/`.
4. **Streaming:** o cache/conector é local ao processo. Execute exatamente **uma réplica por
   credencial Socket**; múltiplas réplicas fariam logins paralelos, podendo derrubar ou bloquear a
   conta. Configure somente os hosts Crystal documentados e use `datafeed2` apenas como failover.

## Testes

```powershell
pytest          # 139 testes: auth, entitlements, REST, Trading, Socket Crystal/cache e login — mockados
ruff check .
python scripts/smoke_live.py     # smoke REST real; pula sozinho sem credenciais
```

## Pendências (perguntar ao Saulo/Adriel)

Decisões já fechadas: credencial downstream = do próprio cliente; entitlement comercial = incluído
no contrato Market Data, sem SKU novo; transporte do MVP = remoto, Streamable HTTP. O que resta é
pauta da Cedro, não do MCP — ver Gap Analysis em `docs/arquitetura/`:

- IAM: URL de produção, validação por **JWKS** ou **introspection**, nomes reais dos `roles`/`claims`.
- API key: o IAM emite/gerencia, ou criamos o store?
- Cota por plano (20k/100k/500k req/mês): não é aplicada em lugar nenhum hoje — sem dono.
- Credencial Crystal de homologação para executar o gate TCP real; os hosts/porta já estão documentados.

## Próximas fases

A implementação da Fase 2 usa o **Socket Crystal TCP**: handshake por prompts, framing recebido por
`\n`, comandos enviados com `\r\n`, merge incremental de `T:` e os cabeçalhos `Z:`/`V:` para book/fita.
O próximo gate é validá-la com credencial de homologação; depois vêm Conta/Análise e
Cadastro/Backoffice.
