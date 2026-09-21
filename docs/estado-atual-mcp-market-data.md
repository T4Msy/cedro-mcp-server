# Estado atual — MCP Server de Market Data

## O que é

Um servidor MCP (Model Context Protocol) que expõe a API Market Data da Cedro como *tools* de
leitura pra IAs — cotações, candles, book, negócios, rankings e notícias. A arquitetura segue o
modelo de **1 MCP por produto**: este cobre só Market Data. WebFeed e os demais produtos
(Trading, Conta/Análise, Cadastro/Backoffice) ficam isolados em servidores próprios, mais adiante.

## O que já está construído

26 tools no total — 17 de cotações/candles/book/negócios/rankings e 9 de notícias — mais os
recursos de documentação expostos como `cedro-docs://`. Todas as tools são de leitura pura; não
há nenhuma ação de escrita/execução neste MCP (isso fica reservado pro futuro MCP de Trading).

- **Auth do chamador**: JWT via IAM da Cedro (Identity Server) ou API key pra automação/robôs.
  Autorização por escopo — o cliente só enxerga e só executa as tools do plano contratado
  (`marketdata:read` pras 17 tools de mercado, `marketdata:news` pras 9 de notícias).
- **Transporte Streamable HTTP** — cliente conecta só com URL + token, sem instalar nada.
  `stdio` também está disponível, mas só pra uso em desenvolvimento local.
- **Rate limit por token**, aplicado via middleware.
- **Credencial downstream desacoplada por interface** (`CredentialProvider`): decidido — credencial
  do próprio cliente (a `PerUserCredentialProvider`, enviada por requisição); `ServiceAccountCredentialProvider`
  fica só para desenvolvimento local (detalhe abaixo).
- **68 testes automatizados** (auth, entitlements, sessões, parsing, HTTP, resources), todos passando.

A implementação está estável e organizada. O que falta pra considerar isso pronto pra cliente
não é código — são decisões de produto/infra ainda em aberto, listadas abaixo.

## Por que foi feito assim

- **Streamable HTTP em vez de SSE**: SSE é o transporte legado do protocolo MCP. Streamable HTTP
  atende o mesmo requisito prático (URL + token, zero instalação, rate limit) sem já nascer
  obsoleto. Decidido: MVP remoto em Streamable HTTP desde já (`MCP_TRANSPORT` agora rejeita
  `"sse"` explicitamente em vez de tratá-lo como Streamable HTTP em silêncio).
- **Credencial plugável em vez de hardcoded**: a interface (`CredentialProvider`) permitiu decidir
  o modelo (credencial do próprio cliente, por requisição) sem reescrever o resto do servidor —
  troca-se só a implementação (`PerUserCredentialProvider`).
- **Auth por escopo/entitlement**: pensado pra já sustentar múltiplos planos (ex.: cliente que só
  contratou cotações não enxerga nem executa as tools de notícias).

## O que falta validar

**Nunca rodou contra a API real da Cedro.** Os 68 testes usam mocks/fixtures. Existe um script
de validação contra o ambiente real (`smoke_live.py`), mas ele pula automaticamente quando não
encontra credencial de sandbox — e ainda não recebemos uma pra rodar de verdade. Ou seja: o
código faz o que os testes descrevem, mas o comportamento contra o Market Data real (parsing de
resposta real, sessão, rate limit do lado deles) ainda não foi confirmado.

## O que precisa ser decidido antes de ir pra produção

**Decidido** (ver `docs/arquitetura/`): transporte remoto Streamable HTTP desde o MVP; credencial
downstream = a do próprio cliente, enviada por requisição; entitlement comercial incluído no
contrato Market Data, sem SKU novo. O que resta:

1. **Credencial de sandbox** pra rodar a validação contra a API real antes de qualquer deploy de
   produção (`scripts/smoke_live.py`).
2. **IAM de produção**: URL definitiva, validação por JWKS ou introspection, e os nomes reais dos
   `roles`/`claims` (hoje são provisórios).
3. **Rate limit**: por token, por conta ou por `client_id`? Existe limite diferente por plano?
   (Hoje o rate limit é em memória por processo — com múltiplas réplicas o limite efetivo escala
   com o número de réplicas, não é um limite global; pra isso, precisaria de um backend
   compartilhado tipo Redis.)
4. **Cota por plano e redistribuição**: pauta comercial ainda sem dono — ver Gap Analysis e a nota
   **REQUIRES LEGAL/COMMERCIAL VALIDATION** em `docs/arquitetura/`.
