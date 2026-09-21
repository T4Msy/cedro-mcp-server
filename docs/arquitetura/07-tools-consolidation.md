# Tools — consolidação (trabalho futuro, não desta rodada)

## O problema

As 26 tools atuais são espelho 1:1 dos endpoints REST — exatamente o padrão que o brief original
pede para evitar. A regra a seguir num refactor futuro: **uma tool por operação que um humano
pediria**, não uma tool por rota HTTP. O padrão já existe no repositório em `tools/book.py`
(`md_get_book(symbol, kind)` — um parâmetro `kind` no lugar de três tools `full`/`aggregated`/
`mini`); é esse padrão que deve se espalhar para o resto.

## Alvo: ~13-15 tools (de 26)

| Grupo hoje | Tools hoje | Consolidação proposta |
|---|---|---|
| Notícias | 9 (`news_get_last`, `news_get_by_code`, `news_by_date`, `news_by_agency`, `news_relevant_facts`, `news_relevant_facts_by_quote`, `news_list_agencies`, `news_search`, `news_relevant_facts_by_agency`) | **→ 3**: buscar notícias (unifica last/by_date/by_agency/search/query por parâmetros opcionais), ler uma notícia (by_code), listar agências |
| Candles | 2 (`md_get_candles_last`, `md_get_candles_range`) | **→ 1**: um parâmetro de modo (`last` com `count` vs. `range` com `start`/`end`) |
| Negócios (fita) | 2 (`md_get_trades_range`, `md_get_trades_date`) | **→ 1**, mesmo padrão |
| Altas/baixas (movers) | 2 (`md_get_gainers`, `md_get_losers`) | **→ 1**: parâmetro de direção |
| Book (DOM) | 1 (já consolidado) | Sem mudança — é o modelo a seguir |
| Cotações & ativos | 7 (`md_get_quote`, `md_get_quote_info`, `md_list_markets`, `md_list_indices`, `md_get_index_assets`, `md_get_company_quotes`, `md_list_options`) | Sem consolidação óbvia — são operações distintas o suficiente; manter como estão |
| Rankings/Volume | 3 (`md_get_player_ranking`, `md_get_cross_ranking`, `md_get_volume_at_price`) | Sem consolidação óbvia — operações distintas |

Total após consolidação de notícias/candles/negócios/movers: 26 − (9−3) − (2−1) − (2−1) − (2−1) = **~15**.

## Por que fica fora desta rodada

Esta entrega é saneamento (corrigir defeitos, fechar o vazamento de segurança, unificar a base de
código) e dossiê de arquitetura — não refactor de superfície de API. Consolidar tools muda o
contrato que um cliente MCP já vê (mesmo que nenhum esteja em produção ainda), e deve ser feito como
mudança deliberada, com seu próprio ciclo de teste, não misturada a correções de segurança/
higiene. Fica registrado aqui como o próximo passo de produto depois desta rodada.
