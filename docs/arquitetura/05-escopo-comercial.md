# Nota de escopo comercial — este MCP atende só clientes REST

**Precisa estar escrito e comunicado antes de alguém vender este MCP para um cliente Socket.**

## O fato

`_shared/REGRAS-DA-API.md` (skill pública `market-data-rest`) registra, junto com a mineração de
chamados de suporte real: **REST e Socket são planos mutuamente exclusivos por login.** Um login
contratado para REST recebe *"You don't have any permission for this software."* se a mesma
credencial tentar autenticar no Socket, e vice-versa.

Como a Alternativa A de credencial downstream (`06-credential-transport.md`) usa **a credencial que
o cliente já tem para a Market Data REST**, isso implica diretamente: **um cliente que só contratou
SOCKET/SOCKETLIB não tem uma credencial que funcione neste MCP.** Não é uma limitação de
implementação — é uma limitação de identidade herdada da própria Market Data.

## Consequência prática

- Antes de oferecer este MCP a um cliente, confirmar que o plano dele inclui REST (ou solicitar/
  provisionar uma credencial REST adicional, se a Cedro permitir contratar os dois canais).
- Um cliente Socket que quer o equivalente deste produto precisa do **futuro MCP de streaming (F2)**
  — candidato natural é a [[API WebSocket (WebFeeder)]], que já entrega JSON sem o parser TCP do
  protocolo Crystal, citada no roadmap como candidata preferencial para F2.
- Isso deve estar em qualquer material de venda/onboarding deste MCP, não só neste dossiê técnico.

## O que este documento não decide

Se vale a pena a Cedro oferecer, comercialmente, a opção de "credencial REST extra só para usar o
MCP" a um cliente que só tinha Socket antes — essa é uma decisão comercial (parte da pauta de
Saulo/Adriel em `04-gap-analysis.md`), não uma decisão de arquitetura deste MCP.
