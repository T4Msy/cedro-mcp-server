# Trading — autenticação e status de validação

Registro do que está implementado no cliente Trading (`src/cedro_mcp/trading/`, Fase 1 do
roadmap "Cedro Connect IA" — ver `08-plano-por-fases.md`) e o que ainda não foi confirmado
contra a API real.

## As 3 camadas (implementadas)

1. `POST /SignIn` — mesma credencial-conceito da Market Data REST, mas conta OMS separada
   (`TradingCredentials`, nunca a mesma instância de `RestCredentials`).
2. `GET /services/negotiation/brokerServiceLogin?appname=...&username=...` — sempre GET (a
   variante POST documentada responde 405 em campo, segundo a skill). Manda o `username` na
   query **e** o header `user-identifier` — omitir o `username` é a causa mais comum e
   documentada de `code 3`, mesmo com o header corretamente montado.
3. Header `user-identifier` em toda chamada de negociação subsequente — JSON
   `{id, user_name, login_oms, password, remote_ip}` codificado.

## BASE64 vs. RSA — status de validação

- **BASE64**: default (`CEDRO_TRADING_ENCRYPTION=base64`), implementado e testado (mock) em
  `tests/test_trading_identity.py`. É o formato confirmado em campo pela skill
  (`exemplo-csharp/UserIdentifier.cs` usa só isso).
- **RSA-OAEP-SHA256** (`CEDRO_TRADING_ENCRYPTION=rsa`): implementado pela especificação da
  skill (`AUTENTICACAO.md`) — busca o JWKS em `CEDRO_TRADING_JWKS_URL`, monta a chave pública
  de `keys[0]`, cifra com OAEP/SHA-256, base64 do resultado. **Nunca confirmado contra o
  Identity Server real** — testado só com um par de chaves gerado localmente
  (`test_encode_rsa_can_be_decrypted_with_the_matching_private_key`), provando que a
  cifragem em si está correta, não que o formato bate com o que a Cedro espera do outro lado.
  Antes de habilitar em produção: validar contra `sso-sandbox.cedrotech.com` com uma conta
  que a Cedro confirme estar configurada para RSA.

## O que nunca rodou contra a API real

Igual ao estado documentado em `04-gap-analysis.md`/`08-plano-por-fases.md`: `TradingClient`
tem cobertura de teste completa **com mocks** (`tests/test_trading_client.py`,
`test_trading_tools.py`) — handshake completo, disambiguação de 401 (sessão vs. `code 24`),
`code 3` do `brokerServiceLogin`, gate `preview→confirm`. **Nenhuma chamada real foi feita
contra `wfcertificacao.cedrotech.com` ou produção.** `cedro-trading-smoke/` (harness C# já
existente, dry-run por padrão) é o gate recomendado antes de expor `trading_confirm` a
qualquer uso real — rodar esse harness contra uma conta de homologação primeiro, comparar o
comportamento observado com o que este cliente Python assume, só então confiar no fluxo.

## `remote_ip` e `sourceaddress`

A Cedro usa esses campos para rastreabilidade da ordem — não são cosméticos. Hoje
(`CEDRO_TRADING_REMOTE_IP`, default `"0.0.0.0"`) é um placeholder deliberadamente óbvio (nunca
`127.0.0.1`, que passaria despercebido como IP real). Antes de produção real, decidir o que
esse campo deve conter de fato: o IP do servidor MCP (quem está de fato chamando a Cedro) é a
leitura mais literal da documentação ("IP de origem da requisição"), mas vale confirmar com a
Cedro se eles esperam algo que identifique o usuário final em vez do servidor.
