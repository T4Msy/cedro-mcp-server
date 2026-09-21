# Commercial / Entitlement

## Decidido

**O MCP entra incluído no contrato Market Data** — sem SKU novo, sem flag comercial nova. Quem já
contrata Market Data REST pode usar este MCP com a própria credencial; não há um produto separado a
vender, negociar ou provisionar para habilitá-lo. Isso é consistente com a escolha de credencial
downstream (`06-credential-transport.md`): como a autorização real acontece na Market Data REST (o
401 dela), o MCP não introduz um novo ponto de controle comercial — ele reusa o que já existe.

Isso simplifica a autorização do lado do MCP: `auth/entitlements.py` continua controlando **acesso
ao serviço MCP em si** (quem pode conectar, rate limit por cliente), não **o que o dado retorna**
— essa parte já é resolvida pela API.

## Um buraco herdado, sem prazo definido — não resolvível pelo MCP sozinho

### Cota por tier sem dono

A documentação de provisionamento registra três tiers comerciais (20k/100k/500k req/mês), mas o
texto do próprio provisionamento diz que aplicar cota por tier é "responsabilidade de outro
sistema" — sistema que, até este discovery, **não existe e não tem dono**. Hoje nenhuma cota é
aplicada em lugar nenhum. Isso não é um bug do MCP: é uma lacuna de plataforma que precede o MCP e
que o MCP sozinho não pode fechar (ele não é o sistema de billing/quota da Cedro).

**Decisão do usuário (21/09):** sem prazo — "isso é quando eu quiser". Não é bloqueio nem pauta
urgente; fica registrado, sem dono, para quando ele decidir priorizar. Ver `04-gap-analysis.md`.

## Redistribuição / display vs. non-display — fechado, não se aplica

Busca em todo o material interno e de cliente (vault + `cedro-api-skills`) não encontrou nenhum
documento próprio sobre redistribuição de dados de mercado, distinção display/non-display, ou
obrigação regulatória B3 associada ao consumo via API — mas isso não vira um bloqueio deste MCP.

**Decisão do usuário (21/09):** "nem vai ter, isso é pelo Market Data" — a responsabilidade por
redistribuição/display já é coberta pelo contrato/termos da própria Market Data (o cliente que
redistribui dado já está sujeito às regras dela, independente de consumir via REST direta ou via
este MCP). O MCP não introduz uma obrigação nova nem precisa de uma regra própria. Marcação
**REQUIRES LEGAL/COMMERCIAL VALIDATION** removida — ponto encerrado.
