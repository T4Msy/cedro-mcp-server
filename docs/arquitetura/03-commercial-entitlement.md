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

## Dois buracos herdados — não resolvidos nesta rodada, não resolvíveis pelo MCP sozinho

### 1. Cota por tier sem dono

A documentação de provisionamento registra três tiers comerciais (20k/100k/500k req/mês), mas o
texto do próprio provisionamento diz que aplicar cota por tier é "responsabilidade de outro
sistema" — sistema que, até este discovery, **não existe e não tem dono**. Hoje nenhuma cota é
aplicada em lugar nenhum. Isso não é um bug do MCP: é uma lacuna de plataforma que precede o MCP e
que o MCP sozinho não pode fechar (ele não é o sistema de billing/quota da Cedro). Fica registrado
como item de pauta para Saulo/Adriel — ver `04-gap-analysis.md`.

### 2. Ausência de regra de redistribuição / display vs. non-display

Busca em todo o material interno e de cliente (vault + `cedro-api-skills`) não encontrou **nenhum**
documento sobre redistribuição de dados de mercado, distinção display/non-display, ou obrigação
regulatória B3 associada ao consumo via API. O MCP muda a forma como o dado é distribuído — de uma
chamada HTTP direta do cliente para uma resposta mediada por um agente de IA, potencialmente
reexibida, resumida ou repassada por esse agente — o que é exatamente o tipo de mudança que esse
tipo de obrigação regulatória costuma cobrir.

> ⚠️ **REQUIRES LEGAL/COMMERCIAL VALIDATION.** Este dossiê não resolve esse ponto por conta própria
> — não há informação suficiente no material disponível para tomar essa decisão, e é uma decisão
> que tem consequência regulatória/contratual, não só técnica. Fica registrado como bloqueio a
> esclarecer antes de qualquer divulgação ampla do produto, separado da pauta técnica de
> Saulo/Adriel.
