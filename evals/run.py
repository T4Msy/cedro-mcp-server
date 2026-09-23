"""Roda os evals de comportamento contra a API da Claude.

    python -m evals.run                   # todos os cenários
    python -m evals.run nao_inventa_preco # só os nomeados
    CEDRO_EVAL_MODEL=claude-sonnet-5 python -m evals.run

Credencial: ANTHROPIC_API_KEY (ou perfil do `ant auth login`). Custa tokens de verdade — cada
cenário faz algumas chamadas ao modelo; o total gasto é impresso no fim. Grava o relatório em
evals/results/<timestamp>.json. Sai com código 1 se algum cenário crítico falhar.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from .harness import DEFAULT_MODEL, build_eval_server, run_conversation
from .mocks import CedroMock
from .scenarios import SCENARIOS, Scenario

RESULTS_DIR = Path(__file__).parent / "results"


def run_scenario(api: object, scenario: Scenario, model: str) -> dict:
    mock = CedroMock()
    with mock.active():
        mcp = build_eval_server()
        trace = run_conversation(api, mcp, scenario.user_messages, model=model)  # type: ignore[arg-type]
    checks = [check(trace) for check in scenario.checks]
    return {
        "scenario": scenario.name,
        "description": scenario.description,
        "critical": scenario.critical,
        "passed": all(ok for ok, _ in checks),
        "checks": [{"ok": ok, "detail": detail} for ok, detail in checks],
        "tool_calls": [{"name": c.name, "input": c.input, "is_error": c.is_error,
                        "user_turn": c.user_turn} for c in trace.calls],
        "replies": trace.replies,
        "served_by_fallback": trace.served_by_fallback,
        "stop_reasons": trace.stop_reasons,
        "usage": {"input_tokens": trace.input_tokens, "output_tokens": trace.output_tokens},
        "orders_sent_to_oms": mock.orders,
    }


def main(argv: list[str]) -> int:
    import anthropic

    model = os.environ.get("CEDRO_EVAL_MODEL", DEFAULT_MODEL)
    selected = [s for s in SCENARIOS if not argv or s.name in argv]
    if not selected:
        print(f"Nenhum cenário com esses nomes. Disponíveis: {[s.name for s in SCENARIOS]}")
        return 2

    api = anthropic.Anthropic().beta.messages
    results = []
    for scenario in selected:
        try:
            result = run_scenario(api, scenario, model)
        except anthropic.APIError as exc:
            result = {"scenario": scenario.name, "critical": scenario.critical, "passed": False,
                      "checks": [{"ok": False, "detail": f"erro da API: {exc}"}]}
        results.append(result)
        mark = "OK  " if result["passed"] else ("FALHA" if scenario.critical else "aviso")
        print(f"[{mark}] {scenario.name}")
        for check in result["checks"]:
            print(f"        {'✓' if check['ok'] else '✗'} {check['detail']}")
        if result.get("served_by_fallback"):
            print("        ! servido pelo modelo de fallback — não mediu o modelo pedido")

    tokens_in = sum(r.get("usage", {}).get("input_tokens", 0) for r in results)
    tokens_out = sum(r.get("usage", {}).get("output_tokens", 0) for r in results)
    passed = sum(r["passed"] for r in results)
    print(f"\n{passed}/{len(results)} cenários passaram · modelo {model} · "
          f"{tokens_in:,} tokens de entrada, {tokens_out:,} de saída")

    RESULTS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report = RESULTS_DIR / f"{stamp}.json"
    report.write_text(
        json.dumps({"model": model, "results": results}, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(f"Relatório: {report}")
    return 1 if any(not r["passed"] and r["critical"] for r in results) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
