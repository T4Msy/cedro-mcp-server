# Estado atual — Cedro Connect IA / Market Data MCP

## O que está construído

O servidor MCP expõe três superfícies da Cedro para IAs:

- **Market Data REST:** 26 tools somente-leitura para cotações, candles, livro, negócios, rankings e notícias.
- **Streaming Socket Crystal (Fase 2):** 5 tools `stream_*` para cotação, livro agregado, fita, cancelamento de assinatura e status. Uma conexão TCP é compartilhada por hash de credencial Socket dentro do processo; o cache nunca é compartilhado entre contas.
- **Trading (Fase 1):** 2 tools de consulta e 4 ferramentas de ação protegidas por `preview → confirm`, com token de uso único.

Há 139 testes automatizados para autenticação, escopos, REST, Socket Crystal/cache, login web e Trading; `ruff check .` está limpo.

## Limites e proteções relevantes

- REST, Socket e Trading usam credenciais separadas. O login pelo navegador aceita qualquer combinação dos três produtos; uma conta Socket não precisa possuir credencial REST.
- As tools de streaming exigem `marketdata:stream`. O cache/conector só abre quando uma tool que precisa de dados é chamada; `stream_status` não cria login nem conexão.
- `CEDRO_CRYSTAL_HOST` usa `crystalhomologacao.cedrotech.com` em homologação ou `datafeed1.cedrotech.com,datafeed2.cedrotech.com` em produção; `CEDRO_CRYSTAL_PORT=81`.
- O processo mantém exatamente uma conexão por credencial; em queda, tenta failover com backoff mínimo de 3 segundos e nunca repete `Invalid Login` automaticamente.
- `CEDRO_CRYSTAL_SOFTWARE_KEY` é opcional; software key vazia é enviada como primeira linha do handshake.

## Validação pendente

A Fase 2 está validada com transporte fake/fixtures, mas ainda não contra o Socket Crystal real. O gate requer:

1. Host/porta Crystal de homologação ou produção (`crystalhomologacao.cedrotech.com:81` ou `datafeed1/datafeed2:81`).
2. Credencial Socket de teste, distinta da REST.
3. Confirmação ao vivo do handshake e das mensagens `T:`, `Z:` e `V:`, em especial a semântica dos campos da fita.
4. Confirmação do limite numérico de conexões por conta antes de qualquer escala horizontal.

Trading também permanece bloqueado para uso real até executar o harness de homologação descrito em `docs/arquitetura/10-trading-auth.md`.

## Fora do escopo atual

IAM de produção, API keys gerenciadas, cota global por plano, Conta/Análise e Cadastro/Backoffice seguem como decisões/produtos separados. Ver `docs/arquitetura/`.
