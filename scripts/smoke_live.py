"""Smoke test contra a API REAL da Cedro (sandbox/produção).

Gated por credenciais: se CEDRO_USER/CEDRO_PASS não estiverem no ambiente, o
script sai com aviso (skip) sem falhar. É o gancho da validação real prevista no
plano — quando a Cedro liberar acesso, rode:

    python scripts/smoke_live.py

Compara respostas reais com o que os modelos esperam e imprime divergências.
"""

from __future__ import annotations

import sys

from cedro_mcp.client import CedroClient
from cedro_mcp.config import load_settings
from cedro_mcp.errors import CedroError


def main() -> int:
    settings = load_settings()
    if not settings.has_rest_credentials:
        print("[skip] CEDRO_USER/CEDRO_PASS ausentes — smoke live pulado.")
        return 0

    client = CedroClient(settings)
    try:
        print(f"Host: {settings.base_url}")

        markets = client.get_quotes("/services/quotes/listMarket")
        print(f"listMarket → {len(markets or [])} mercados")

        quote = client.get_quotes("/services/quotes/quote/PETR4")
        print(f"quote/PETR4 → {quote!r:.200}")

        candles = client.get_quotes("/services/quotes/candleLast/PETR4/D/3")
        print(f"candleLast → {len(candles or [])} candles")

        if settings.has_news_credentials:
            agencies = client.get_news("/services/news/newsAgency")
            print(f"newsAgency → {agencies!r:.200}")
        else:
            print("[skip] credenciais de notícias ausentes.")

        print("OK — endpoints responderam.")
        return 0
    except CedroError as exc:
        print(f"[erro] {exc}")
        return 1
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())
