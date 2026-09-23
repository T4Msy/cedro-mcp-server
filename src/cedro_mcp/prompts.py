"""Prompts MCP — roteiros prontos para os fluxos mais comuns, escolhidos pelo usuário no cliente.

MCP prompts: ready-made workflows the user picks in the client (Claude Desktop mostra como
"atalhos"). Só orientam o modelo sobre QUAIS tools chamar e em que ordem — não executam nada, e
as tools continuam sujeitas aos escopos do plano de cada um.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def register(mcp: "FastMCP") -> None:
    @mcp.prompt(title="Análise rápida de um ativo")
    def analise_de_ativo(symbol: str) -> str:
        """Panorama de um ativo: cotação, tendência recente, livro e notícias."""
        return (
            f"Faça um panorama objetivo do ativo {symbol} usando as tools da Cedro:\n"
            f"1. md_get_quote(['{symbol}']) — último preço, variação do dia e volumes.\n"
            f"2. md_get_candles(symbol='{symbol}', period='D', mode='last', count=30) — "
            "tendência dos últimos 30 pregões (máxima, mínima, direção).\n"
            f"3. md_get_book(symbol='{symbol}', kind='aggregated') — pressão compradora x "
            "vendedora no topo do livro.\n"
            f"4. news_search(keyword='{symbol}', count=10) — notícias recentes (pule se a tool "
            "não estiver disponível no plano).\n"
            "Apresente em seções curtas, com os números que vieram das tools, e diga quando um "
            "dado não estiver disponível. Não faça recomendação de compra ou venda."
        )

    @mcp.prompt(title="Revisar minhas ordens de hoje")
    def revisar_ordens_do_dia(account: str, market: str = "XBSP") -> str:
        """Revisão das ordens do dia: executado, em aberto e rejeitado."""
        return (
            f"Revise as ordens de hoje da conta {account} no mercado {market}:\n"
            f"1. trading_get_day_summary(account='{account}', market='{market}') — comprado/"
            "vendido por ativo, preço médio e ordens em aberto.\n"
            f"2. trading_list_orders_today(account='{account}', market='{market}') — detalhe de "
            "cada ordem, para explicar rejeições (use o texto do OMS) e listar as abertas com "
            "clordid, quantidade restante e preço.\n"
            "Resuma: o que executou, o que segue aberto e o que foi rejeitado e por quê. Lembre "
            "que isso NÃO é custódia — são só as ordens de hoje. Não cancele nem edite nada sem "
            "o usuário pedir; se pedir, use trading_preview_* e espere a confirmação explícita."
        )

    @mcp.prompt(title="Montar uma ordem com confirmação")
    def preparar_ordem(pedido: str) -> str:
        """Transforma um pedido em linguagem natural numa ordem, sempre via preview + confirmação."""
        return (
            f'O usuário pediu: "{pedido}".\n'
            "Monte a ordem com segurança:\n"
            "1. Se faltar ativo, lado (compra/venda), quantidade, conta, mercado ou tipo/preço, "
            "pergunte antes de seguir — não invente valores.\n"
            "2. Consulte md_get_quote do ativo para mostrar o preço atual ao usuário.\n"
            "3. Chame trading_preview_order. Mostre o `summary`, o `estimated_value` e TODOS os "
            "`warnings` exatamente como vieram.\n"
            "4. Pergunte explicitamente se pode enviar. Só chame trading_confirm com o "
            "confirmation_token depois de um 'sim' claro nesta conversa, agora.\n"
            "5. Depois do confirm, confira o status real com trading_list_orders_today."
        )
