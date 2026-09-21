# Reuse Map

O que este MCP precisa e onde já existe — a resposta é "reutilizar" em quase tudo. Nada abaixo é uma
proposta de construção nova; é um inventário do que o discovery encontrou já pronto.

| Necessidade | Já existe em | Estado |
|---|---|---|
| Cliente REST (auth `SignIn`/`JSESSIONID`, cliente OAuth2 de Notícias) | `src/cedro_mcp/client.py`, `sessions.py` | Pronto, testado com mocks |
| Contrato de endpoints (paths, params, formatos de data) | `cedro-api-skills/.../market-data-rest/_shared/references/ENDPOINTS.md` | Curado, público, base do `resources.py` |
| Regras operacionais (retry, `SignIn` sem loop, formatos de erro) | `.../market-data-rest/_shared/REGRAS-DA-API.md` | Curado, público |
| Auth do chamador (IAM JWT + API key) | `src/cedro_mcp/auth/token_verifier.py`, `api_key.py` | Pronto |
| Modelo de entitlement (escopo → tool, 2 camadas) | `src/cedro_mcp/auth/entitlements.py`, `scopes.py` | Pronto, nomes de escopo provisórios |
| Decisões de arquitetura (1 MCP por produto, Streamable HTTP, IAM+API key) | `API's Cedro/99-Roadmap/Arquitetura do MCP (...).md` (reunião Tales×Adriel) | Já decidido, implementado |
| Decisão de credencial downstream via elicitation (produto "Advisor") | `API's Cedro/99-Roadmap/Cedro Advisor MCP - Produto, Acesso e Guardrails.md` | Precedente direto para a Alternativa B (evolução) deste MCP |
| Catálogo de tools por fase (F1–F5) | `API's Cedro/99-Roadmap/Especificacao do MCP Server (blueprint).md` | F1 (Market Data REST) é o que este MCP cobre |
| Schemas Pydantic de resposta | `src/cedro_mcp/models.py` | Pronto, cobre os 26 endpoints atuais |
| Rate limit por token | `src/cedro_mcp/http_app.py` (middleware ASGI) | Pronto — em memória, por processo (ver `02-security-model.md`) |
| CI / lint / testes | `.github/`, `pyproject.toml`, `tests/` (139 testes) | Pronto |
| Deploy (Docker + Render) | `Dockerfile`, `Market Data/render.yaml`, `Market Data/DEPLOY-RENDER.md` | Existe mas apontava para a cópia errada — corrigido nesta rodada |

## O que não existe e precisa ser construído (fora desta rodada)

- `PerUserCredentialProvider` real (hoje stub) — implementação da Alternativa A (`06-credential-
  transport.md`).
- Limitador de `SignIn` por login/hash de credencial.
- Consolidação de tools (26 → ~13-15) — ver `07-tools-consolidation.md`.
- `scripts/smoke_live.py` contra a API real — próxima rodada, fora do escopo atual.
