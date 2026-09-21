# Cedro MCP Server — Market Data

Servidor **MCP** que expõe a API **Market Data** da Cedro como *tools* de leitura pura para IAs.
Segue o modelo **1 MCP por produto** decidido em reunião: este servidor cobre **apenas** Market Data.

> **Status:** construído e testado com **mocks/fixtures** (68 testes). Ainda **não validado contra a
> API real da Cedro** — falta credencial de sandbox. Ver `scripts/smoke_live.py`. Arquitetura e
> decisões comerciais documentadas em `docs/arquitetura/`.

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

`marketdata:read` é exigido para conectar ao servidor. Nomes **provisórios** até a Cedro confirmar os
`roles`/`claims` reais do IAM — o único ponto de verdade é `src/cedro_mcp/auth/scopes.py`.

## Tools (26)

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

## Testes

```powershell
pytest          # 68 testes: auth, entitlements, sessões, HTTP, parsing, resources — tudo mockado
ruff check .
python scripts/smoke_live.py     # validação real; pula sozinho sem credenciais (próxima rodada)
```

## Pendências (perguntar ao Saulo/Adriel)

Decisões já fechadas: credencial downstream = do próprio cliente; entitlement comercial = incluído
no contrato Market Data, sem SKU novo; transporte do MVP = remoto, Streamable HTTP. O que resta é
pauta da Cedro, não do MCP — ver Gap Analysis em `docs/arquitetura/`:

- IAM: URL de produção, validação por **JWKS** ou **introspection**, nomes reais dos `roles`/`claims`.
- API key: o IAM emite/gerencia, ou criamos o store?
- Cota por plano (20k/100k/500k req/mês): não é aplicada em lugar nenhum hoje — sem dono.
- Redistribuição/display-vs-non-display: nenhum documento existe — **REQUIRES LEGAL/COMMERCIAL
  VALIDATION**.
- Escopo do 2º MCP (**WebFeed**/streaming) e limite de conexões simultâneas do Market Data.

## Próximas fases

F2 streaming (a [API WebSocket](../API's%20Cedro/10-Geral-e-Conexao/API%20WebSocket%20(WebFeeder).md)
entrega JSON, sem o parser TCP do Crystal — candidata preferencial), depois Trading (com confirmação
por ordem), Conta/Análise e Cadastro/Backoffice.
