# Executive Summary — Cedro Market Data MCP

## O que é

O **Cedro Market Data MCP** é uma interface MCP oficial sobre a **Market Data REST** da Cedro. Não é
um produto novo — é a forma de um cliente (ou o agente de IA que ele usa: Claude, ChatGPT, Codex,
Cursor) consumir a mesma Market Data REST que ele já contrata hoje, por Streamable HTTP em vez de
chamadas HTTP manuais.

## Onde este dossiê chega

O trabalho começou como "desenhar um MCP do zero" e virou, no discovery, outra coisa: **o produto já
está ~70% construído** em `cedro-mcp-server/` — 26 tools, auth de chamador por IAM/API key,
entitlements por escopo em dois níveis, rate limit, Dockerfile, CI. O que faltava não era código de
MCP — eram quatro decisões paradas desde julho ("pendências com o Saulo/Adriel") e um conjunto de
defeitos que bloqueavam qualquer deploy. As quatro decisões:

| Decisão | Escolha |
|---|---|
| Credencial downstream | **Credencial do próprio cliente** (o `md_xxxx` que ele já contratou) |
| Entitlement comercial | **Incluído no contrato Market Data** — sem SKU novo, sem flag nova |
| Transporte do MVP | **Remoto, Streamable HTTP**, desde já |
| Escopo desta entrega | **Dossiê de arquitetura + saneamento do repositório** (sem features novas) |

## O que esta entrega faz

1. Registra as quatro decisões e suas consequências técnicas obrigatórias (ver
   `06-credential-transport.md`, `02-security-model.md`).
2. Fecha o achado de maior severidade do discovery: o servidor expunha o **vault interno inteiro**
   (incluindo roadmap e modelo comercial) como resources MCP, sem filtro — corrigido apontando a
   documentação servida para a skill pública `market-data-rest`, não mais para o vault (ver
   `02-security-model.md`).
3. Unifica as duas cópias do servidor sob controle de versão, elegendo a canônica.
4. Corrige um conjunto de defeitos catalogados que impediam merecer um deploy (bug de resource em
   subpasta, transporte "sse" aceito em silêncio, container rodando como root, parâmetros sem
   teto/encoding).
5. Separa claramente **o que falta no MCP** (resolvido nesta rodada) de **o que falta na Cedro**
   (cota por plano sem dono, sem prazo por decisão do usuário) — ver `04-gap-analysis.md`.

## O que esta entrega explicitamente NÃO faz

- Não adiciona features novas nem tools novas.
- Não consolida as 26 tools atuais (ver alvo registrado em `07-tools-consolidation.md`, mas como
  trabalho futuro).
- Não valida contra a API Market Data real — `scripts/smoke_live.py` fica fora desta rodada, por
  escolha explícita, e continua sendo a pendência mais antiga do projeto.

## Consequência comercial que precisa estar escrita antes de vender

**REST e Socket são planos mutuamente exclusivos por login** — confirmado em
`cedro-api-skills/.../market-data-rest/_shared/REGRAS-DA-API.md`: um login contratado para REST
recebe *"You don't have any permission for this software."* se tentar autenticar no Socket, e
vice-versa (mineração de suporte real, não só documentação). O discovery original (sessão anterior,
com acesso ao provisionamento em `market-data/src/cedro/real.ts`) atribui isso ao `broker` do canal
entrando na derivação do login (`md_ + hash(...)`) — não reverifiquei o hash exato nesta rodada por
não ter acesso a esse arquivo, mas a exclusividade de canal em si está confirmada por fonte
independente. **Consequência que se mantém de qualquer forma: este MCP atende só clientes REST.**
Quem contratou SOCKET/SOCKETLIB precisa de um login REST adicional ou do futuro MCP de streaming
(F2) — ver `05-escopo-comercial.md`.
