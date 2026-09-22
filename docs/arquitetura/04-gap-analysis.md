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
| Consolidação de 26 → ~15 tools | **Fechado em 22/09** — 26 → 17 (o alvo original era ~15; ver `07-tools-consolidation.md` para o porquê da diferença). Testes e docs atualizados. |
| Validação contra a API real (`scripts/smoke_live.py`) | **Não fechado nesta rodada**, por escolha explícita — falta credencial de sandbox |

## Falta na Cedro (pauta de Saulo/Adriel, não resolvível pelo MCP sozinho)

Atualizado em 21/09 com respostas diretas do usuário — ver histórico da sessão.

| Item | Status |
|---|---|
| `md_get_gainers`/`md_get_losers` (Altas/Baixas) retornam `401`, resto da API funciona normal na mesma sessão | **Explicado.** O usuário conferiu e a conta de teste está com a flag `professional=false` — é essa a causa provável do 401 nesses endpoints especificamente (produto ligado a conta "profissional"). Não é bug do MCP; se precisar do ranking nesta conta, é pedir a mudança desse flag/plano à comercial da Cedro. |
| Nomes reais dos `roles`/`claims` do IAM, URL de produção do Identity Server | **Parado por decisão do usuário.** "Não veremos nada do IAM ainda, vamos continuar da forma que está sendo feita" (login pelo navegador, `MCP_WEB_LOGIN`) até ele pedir pra retomar. Não é mais pauta ativa. |
| Se a API key é emitida pelo IAM ou por um store próprio do MCP | **Parado junto com o IAM** (item acima) — é pergunta-irmã, mesma decisão de adiar. |
| Cota por tier (20k/100k/500k req/mês) sem sistema/dono | **Sem prazo, por escolha do usuário** — "isso é quando eu quiser". Não é bloqueio nem pauta urgente; fica registrado como pendência sem dono, para quando ele decidir priorizar. |
| Ausência de regra de redistribuição/display-vs-non-display | **Fechado — não se aplica.** O usuário confirmou: "nem vai ter, isso é pelo Market Data" — ou seja, essa responsabilidade já é coberta pelo contrato/termos da própria Market Data (o cliente que redistribui já está sujeito às regras dela), não é algo que o MCP precisa resolver ou que crie uma obrigação nova. Removida a marcação **REQUIRES LEGAL/COMMERCIAL VALIDATION** — ver `03-commercial-entitlement.md`. |
| Escopo do streaming (F2) | **Implementado e validado ao vivo em 22/09** sobre Socket Crystal TCP de produção (`datafeed1/datafeed2:81`): handshake, framing e `stream_get_quote` confirmados com PETR4 real via o conector MCP. `stream_get_book`/`stream_get_tape` ainda não tiveram sessão ao vivo dedicada. |
| Limite de conexões simultâneas do Market Data ao ter múltiplos clientes com sessão própria | **Objetivo aplicado à Fase 2 dentro de um processo:** o registro usa hash da credencial Socket, então tokens/abas com a mesma conta compartilham uma conexão. Continua pendente a regra numérica da Cedro e o mecanismo compartilhado caso haja mais de uma réplica. |

Documentação REST (não Socket) sobre limite de conexões: não existe nota equivalente à de Socket
(`Lidando com o limite de conexao (Socket).md`) para sessões `JSESSIONID` da REST — só a orientação
de não martelar `SignIn` em loop. Confirmado por busca no vault.

## Nota sobre outro Gap Analysis já existente no vault

Existe um documento anterior, `API's Cedro/99-Roadmap/Gap Analysis - Vault vs Site Oficial.md`, que
audita **cobertura de documentação** (vault vs. `docs.cedrotech.com`) — é sobre completude das notas,
não sobre o que falta implementar no MCP. Os dois documentos respondem perguntas diferentes; este
aqui (`04-gap-analysis.md`) é o que importa para a conversa com Saulo/Adriel sobre o MCP.
