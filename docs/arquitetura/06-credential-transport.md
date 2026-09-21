# Decisão de transporte de credencial

## O problema

Com **credencial do próprio cliente** decidida (não service account, não token exchange — ver
`00-executive-summary.md`) e **transporte remoto** decidido, resta um problema real: como a
credencial do cliente chega a um servidor remoto que ele não controla.

## As três alternativas avaliadas

| | Alternativa | Prós | Contras |
|---|---|---|---|
| A | **Header por requisição** — o cliente põe a credencial na config do próprio MCP client; o servidor usa e descarta, nada em repouso | Funciona em 100% dos MCP clients hoje; zero vault de senha; é onde a credencial dele já vive hoje para a REST | A credencial trafega a cada request (sob TLS) e fica num arquivo de config do cliente |
| B | **Elicitation na sessão** — servidor pede login/senha via UI do agente, guarda só em memória da sessão | Nada em arquivo de config, nada em repouso; **precedente direto**: é a alternativa que a nota `Cedro Advisor MCP - Produto, Acesso e Guardrails.md` já escolheu para um produto irmão | Suporte a elicitation é irregular entre MCP clients; exige sessão com estado, e o servidor hoje roda `stateless_http=True` |
| C | **Vault de credenciais + OAuth** | Melhor UX (login uma vez, nunca mais) | Cria a base de senhas de cliente que o roadmap rejeitou explicitamente na nota do Advisor MCP ("nunca existe uma base de senhas de clientes Cedro guardada em algum servidor nosso"); maior superfície de risco de longe |

## Decisão

**A como base do MVP, B como evolução.** C está descartada — pelo mesmo motivo já registrado para o
Advisor MCP: a Cedro não opera hoje como provedor de identidade de trading/market data, e construir
essa ponte para guardar credencial de terceiro é um risco desproporcional para esta entrega.

**Por que A e não B agora:** a credencial já vive num arquivo de config do cliente hoje — é assim
que ele já usa a Market Data REST diretamente. A própria API da Cedro hoje manda login e senha em
**query string** no `SignIn`; um header autenticado é estritamente melhor que o status quo, não uma
regressão de segurança. B não exige nem suporte novo do MCP client, nem infraestrutura nova da
Cedro, nem custódia de senha — as três coisas que travaram este projeto desde julho. B fica como
evolução natural quando/se a repetição de handshake incomodar (o mesmo raciocínio que a nota do
Advisor MCP já registrou sobre elicitation).

## Consequências obrigatórias de A (a implementar antes de produção, fora desta rodada de saneamento)

1. **`PerUserCredentialProvider` deixa de ser stub.** Hoje existe em `credentials.py:63` como
   interface pronta para receber a implementação — a troca é isolada, sem mexer no resto do
   servidor (o mesmo motivo pelo qual a interface foi desenhada assim desde o início).
2. **Sessão `JSESSIONID` cacheada por hash da credencial**, nunca a credencial em si como chave —
   ver `02-security-model.md`, Caso 3.
3. **Store de sessão compartilhado entre réplicas.** `sessions.py` hoje é em memória, por processo
   — sob N réplicas atrás de um load balancer, cada réplica reautenticaria seu próprio cliente,
   multiplicando os `SignIn`s por N. Isso conflita diretamente com o limite de login por conta.
4. **Limitador de `SignIn` por login.** Complementa o cache — mesmo com cache, uma falha de rede
   ou um bug de retry não pode virar uma rajada de `SignIn`s contra a mesma conta.
5. **Credencial fora de log, trace, erro e resposta de tool.** Verificado nesta rodada que hoje não
   há vazamento (busca por `password`/`CEDRO_PASS`) — mas isso precisa continuar sendo um invariante
   verificado a cada mudança em `client.py`/`sessions.py`/`credentials.py`, não uma checagem única.
6. **`stateless_http` revisto.** O servidor hoje assume ausência de estado entre requisições
   (`server.py`); sessão de credencial por cliente é estado. Precisa de decisão explícita sobre como
   isso convive com Streamable HTTP stateless — não é assumido como resolvido por este dossiê.
