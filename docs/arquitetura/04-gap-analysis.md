# Gap Analysis — o que falta no MCP vs. o que falta na Cedro

Separação deliberada: a primeira coluna é trabalho que este repositório pode fechar sozinho (e que
esta rodada de saneamento fecha ou registra como próximo passo técnico). A segunda é pauta que
precisa de uma decisão de negócio ou de outro sistema da Cedro — é a pauta de Saulo/Adriel.

## Falta no MCP (technical debt, resolvível aqui)

| Item | Status após esta rodada |
|---|---|
| Duas cópias do servidor, a boa fora de git | Unificado — `cedro-mcp-server/` é a canônica sob git; `Market Data/mcp-server/` removida |
| Vazamento do vault via `cedro-docs://` | Fechado — docs apontam para a skill pública, não o vault |
| Bug de subpasta no template `cedro-docs://note/{path}` | Corrigido — resolução por token/slug |
| `MCP_TRANSPORT=sse` aceito em silêncio | Corrigido — falha alto no startup |
| Container rodando como root | Corrigido — `USER` não-root no `Dockerfile` |
| `md_get_candles_last(count)` sem teto | Corrigido — mesmo padrão de `Count`/`Limit` de outras tools |
| Interpolação sem encoding em `news_search`/`md_get_quote` | Corrigido |
| README/docs com contagem de testes desatualizada (54 vs. 68) | Corrigido |
| `PerUserCredentialProvider` como stub, não implementação real | **Não fechado nesta rodada** — próximo passo técnico direto, sem dependência externa |
| Consolidação de 26 → ~13-15 tools | **Não fechado nesta rodada** — ver `07-tools-consolidation.md`, é refactor, não saneamento |
| Validação contra a API real (`scripts/smoke_live.py`) | **Não fechado nesta rodada**, por escolha explícita — falta credencial de sandbox |

## Falta na Cedro (pauta de Saulo/Adriel, não resolvível pelo MCP sozinho)

| Item | Por que não é o MCP que resolve |
|---|---|
| Cota por tier (20k/100k/500k req/mês) sem sistema/dono | O MCP não é o sistema de billing/quota; aplicar isso aqui seria reinventar uma responsabilidade que já foi atribuída (mesmo que a atribuição não tenha sido implementada) a "outro sistema" |
| Ausência de regra de redistribuição/display-vs-non-display | Decisão jurídica/regulatória, não técnica — ver `03-commercial-entitlement.md` |
| Nomes reais dos `roles`/`claims` do IAM para escopo MCP | Depende do IAM da Cedro (Saulo); `scopes.py` já isola isso num único ponto de troca |
| URL de produção do Identity Server, JWKS vs. introspection | Depende da infra de IAM da Cedro |
| Se a API key é emitida pelo IAM ou por um store próprio do MCP | Decisão de arquitetura de auth que atravessa mais de um produto |
| Escopo exato do 2º MCP (WebFeed/streaming) | Fora do escopo deste MCP (Market Data F1); é o F2 do blueprint |
| Limite de conexões simultâneas do Market Data ao interagir com sessão por cliente | Depende de como a Cedro dimensiona o lado Market Data, não do MCP |

## Nota sobre outro Gap Analysis já existente no vault

Existe um documento anterior, `API's Cedro/99-Roadmap/Gap Analysis - Vault vs Site Oficial.md`, que
audita **cobertura de documentação** (vault vs. `docs.cedrotech.com`) — é sobre completude das notas,
não sobre o que falta implementar no MCP. Os dois documentos respondem perguntas diferentes; este
aqui (`04-gap-analysis.md`) é o que importa para a conversa com Saulo/Adriel sobre o MCP.
