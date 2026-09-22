# Estado atual — Cedro Connect IA / Market Data MCP

## O que está construído

O servidor MCP expõe três superfícies da Cedro para IAs:

- **Market Data REST:** 17 tools somente-leitura para cotações, candles, livro, negócios, rankings e notícias (consolidado de 26 em 22/09, ver `docs/arquitetura/07-tools-consolidation.md`).
- **Streaming Socket Crystal (Fase 2):** 5 tools `stream_*` para cotação, livro agregado, fita, cancelamento de assinatura e status. Uma conexão TCP é compartilhada por hash de credencial Socket dentro do processo; o cache nunca é compartilhado entre contas.
- **Trading (Fase 1):** 2 tools de consulta e 4 ferramentas de ação protegidas por `preview → confirm`, com token de uso único.

Há 145 testes automatizados para autenticação, escopos, REST, Socket Crystal/cache, login web e Trading; `ruff check .` está limpo.

## Limites e proteções relevantes

- REST, Socket e Trading usam credenciais separadas. O login pelo navegador aceita qualquer combinação dos três produtos; uma conta Socket não precisa possuir credencial REST.
- As tools de streaming exigem `marketdata:stream`. O cache/conector só abre quando uma tool que precisa de dados é chamada; `stream_status` não cria login nem conexão.
- `CEDRO_CRYSTAL_HOST` usa `crystalhomologacao.cedrotech.com` em homologação ou `datafeed1.cedrotech.com,datafeed2.cedrotech.com` em produção; `CEDRO_CRYSTAL_PORT=81`.
- O processo mantém exatamente uma conexão por credencial; em queda, tenta failover com backoff mínimo de 3 segundos e nunca repete `Invalid Login` automaticamente.
- `CEDRO_CRYSTAL_SOFTWARE_KEY` é opcional; software key vazia é enviada como primeira linha do handshake.

## Validação pendente

A Fase 2 foi validada ao vivo em 22/09 contra o Socket Crystal real de **produção**
(`datafeed1.cedrotech.com,datafeed2.cedrotech.com:81`), no deploy Hostinger VPS
(`docs/arquitetura/09-deploy-hostinger-cloudflare.md`): handshake completo e cotação de PETR4
consumida com sucesso pelo conector via `stream_get_quote`. A credencial de Socket usada é a mesma
família de homologação/certificação da conta de teste — funciona em produção mesmo assim.

Ainda em aberto:

1. Confirmação do limite numérico de conexões simultâneas por conta antes de qualquer escala
   horizontal (pauta da Cedro, não técnica — ver `docs/arquitetura/04-gap-analysis.md`).
2. `md_get_book`/`stream_get_book` e a fita (`stream_get_tape`) ainda não tiveram uma sessão ao vivo
   dedicada — só `quote` foi confirmado até agora.

O ambiente de **certificação/homologação** (`wfcertificacao.cedrotech.com`,
`crystalhomologacao.cedrotech.com:81`) está inacessível a partir do IP da VPS
(`2.25.196.22`) — confirmado com diagnóstico de rede em 22/09 (TCP SYN descartado
silenciosamente, assinatura de firewall por allowlist de IP, não instabilidade de rota). Trading
usa exatamente esses hosts e por isso segue bloqueado — ver a seção sobre Trading abaixo.

Trading permanece bloqueado para uso real: a credencial OMS atual é de certificação (confirmado —
`brokerServiceLogin` responde 401 vazio contra produção) e o host de certificação está inacessível
da VPS. Falta liberação de IP da Cedro para `2.25.196.22` **ou** uma credencial de Trading de
produção. Ver também `docs/arquitetura/10-trading-auth.md`.

## Fora do escopo atual

IAM de produção, API keys gerenciadas, cota global por plano, Conta/Análise e Cadastro/Backoffice seguem como decisões/produtos separados. Ver `docs/arquitetura/`.
