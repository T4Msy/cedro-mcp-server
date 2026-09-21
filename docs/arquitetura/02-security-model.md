# Security Model

Threat model construído em cima de três achados concretos deste discovery, não genéricos.

## Caso 1 — Vazamento de documentação interna via `cedro-docs://`

**Achado:** `resources.py` fazia `docs_root.rglob("*.md")` sem filtro, e `config.py` apontava
`CEDRO_DOCS_PATH` por padrão para a raiz inteira deste vault (`"../API's Cedro"`) — que inclui
`99-Roadmap/` (preços por plano, pendências comerciais com Saulo/Adriel), `09-Backoffice-OMS/`
(provisionamento de conta de cliente) e `11-Risk-e-OMS-Broker/`. Publicado remotamente como estava,
**um cliente conectado ao MCP conseguiria ler o roadmap interno da Cedro** via `cedro-docs://index`.

**Correção aplicada nesta rodada:** `CEDRO_DOCS_PATH` default passa a apontar para
`cedro-api-skills/cedro-api-skills/skills/market-data-rest/` — a skill pública, já curada para
cliente, que a Cedro distribui. `resources.py` continua sem lógica de allowlist nova; a superfície
já é o conteúdo certo por construção. Ver `config.py:DEFAULT_DOCS_PATH`.

**Defesa em profundidade que permanece:** mesmo apontando para a pasta certa, o resource
`cedro-docs://note/{token}` resolve por um **mapa token→arquivo** construído a partir dos arquivos
reais (`build_note_map`), não por resolução de path a partir do input do chamador — um token
desconhecido nunca aponta para fora da pasta configurada, por construção (não por uma checagem que
possa ter um buraco).

## Caso 2 — Exclusividade de canal REST/Socket

**Achado:** um login Market Data contratado para REST recebe erro de permissão se usado no Socket, e
vice-versa (confirmado em `_shared/REGRAS-DA-API.md` e na mineração de suporte real). Isso não é uma
vulnerabilidade técnica, mas um limite de produto que o modelo de segurança precisa respeitar: **o
MCP não pode, nem por engano, prometer a um cliente Socket/SOCKETLIB que ele vai conseguir usar a
própria credencial aqui.** Ver nota de escopo comercial em `05-escopo-comercial.md`.

## Caso 3 — Sessão `JSESSIONID` e limite de login por conta

**Achado:** `REGRAS-DA-API.md` registra que reautenticar repetidamente pode levar a **bloqueio
temporário da conta**, e recomenda: no primeiro `401`, invalidar a sessão local e refazer `SignIn`
**uma única vez** — no segundo `401`, parar e reportar, nunca entrar em loop de reautenticação.

**Consequência para um servidor remoto multi-cliente:** com a Alternativa A (credencial do cliente
por requisição, ver `06-credential-transport.md`), cachear o `JSESSIONID` por cliente deixa de ser
otimização de performance e vira **requisito de segurança do cliente** — um `SignIn` por requisição
sob carga pode bloquear a conta dele. Consequências obrigatórias, a implementar antes de produção:
- Sessão `JSESSIONID` cacheada **por hash da credencial** (nunca a credencial em si como chave),
  com store compartilhado entre réplicas (hoje `sessions.py` é em memória, por processo).
- Limitador de `SignIn` por login — não deixar a lógica de retry do cliente MCP martelar o endpoint.
- `stateless_http` (hoje ligado no FastMCP) precisa ser revisto: sessão de credencial por cliente é
  estado, e esse modo assume ausência de estado entre requisições.

## Superfícies já cobertas (sem mudança nesta rodada, registradas para completude)

- **Auth do chamador:** IAM JWT (JWKS) ou API key — `auth/token_verifier.py`, `auth/api_key.py`.
- **Entitlement em duas camadas:** `tools/list` esconde o que não foi contratado; a execução direta
  nega mesmo assim (`auth/entitlements.py`). Esconder ≠ proibir — a segunda camada é a que importa.
- **Anti-DNS-rebinding:** o SDK só liga sozinho em host local; em produção (`0.0.0.0` atrás de LB) é
  preciso configurar `MCP_ALLOWED_HOSTS`/`MCP_ALLOWED_ORIGINS` explicitamente.
- **Rate limit por token**, em memória por processo — com N réplicas o limite efetivo escala com N;
  para limite global, precisa de backend compartilhado (Redis). Não mudou nesta rodada.
- **Credencial fora de log/erro/resposta:** verificado nesta rodada — busca por `password`/
  `CEDRO_PASS` nos caminhos de log e mensagens de exceção não encontrou vazamento (ver seção
  Verificação do plano).
- **Container não-root:** `Dockerfile` rodava como root (sem `USER`) — corrigido nesta rodada.
