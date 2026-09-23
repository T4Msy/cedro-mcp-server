"""O harness de evals funciona sem API: um "modelo" roteirizado exercita o loop, as tools reais
com a Cedro mockada e as checagens — inclusive provando que elas pegam o comportamento errado."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from evals.harness import anthropic_tools, build_eval_server, run_conversation
from evals.mocks import CedroMock
from evals.scenarios import SCENARIOS

_BY_NAME = {s.name: s for s in SCENARIOS}


@dataclass
class _Block:
    type: str
    text: str = ""
    name: str = ""
    input: dict = field(default_factory=dict)
    id: str = ""


@dataclass
class _Response:
    content: list[_Block]
    stop_reason: str
    usage: Any = None


def _tool(name: str, **args: Any) -> _Response:
    return _Response([_Block("tool_use", name=name, input=args, id=f"tu_{name}")], "tool_use")


def _say(text: str) -> _Response:
    return _Response([_Block("text", text=text)], "end_turn")


def _last_tool_result(messages: list[dict]) -> str:
    for message in reversed(messages):
        if message["role"] == "user" and isinstance(message["content"], list):
            return message["content"][-1]["content"]
    return ""


class _ScriptedModel:
    """Cada item do roteiro é uma resposta fixa ou uma função das mensagens."""

    def __init__(self, script: list[Any]) -> None:
        self.script = list(script)
        self.requests: list[dict] = []

    def create(self, **kwargs: Any) -> _Response:
        self.requests.append(kwargs)
        step = self.script.pop(0)
        return step(kwargs["messages"]) if callable(step) else step


_PREVIEW = dict(mode="limit", market="XBSP", symbol="PETR4", side="BUY", qty=100,
                account="10034", price=38.5)


def _confirm_with_preview_token(messages: list[dict]) -> _Response:
    token = None
    for message in messages:
        if message["role"] == "user" and isinstance(message["content"], list):
            for block in message["content"]:
                match = re.search(r'"confirmation_token":\s*"([^"]+)"', block.get("content", ""))
                token = match.group(1) if match else token
    return _tool("trading_confirm", confirmation_token=token)


def _wait_with_clordid(messages: list[dict]) -> _Response:
    clordid = None
    for message in messages:
        if message["role"] == "user" and isinstance(message["content"], list):
            for block in message["content"]:
                match = re.search(r'"clordid":\s*"([^"]+)"', block.get("content", ""))
                clordid = match.group(1) if match else clordid
    return _tool("trading_wait_order_status", account="10034", market="XBSP",
                 clordid=clordid, timeout_seconds=0)


def _run(scenario_name: str, script: list[Any]):  # noqa: ANN202
    scenario = _BY_NAME[scenario_name]
    mock = CedroMock()
    model = _ScriptedModel(script)
    with mock.active():
        trace = run_conversation(model, build_eval_server(), scenario.user_messages,
                                 use_fallbacks=False)
    return scenario, trace, mock, model


def test_tools_are_exported_in_stable_order_with_schemas() -> None:
    tools = anthropic_tools(build_eval_server())
    names = [t["name"] for t in tools]
    assert names == sorted(names)
    assert "trading_confirm" in names and "md_get_indicators" in names
    assert all(t["input_schema"]["type"] == "object" for t in tools)


def test_good_behavior_passes_confirm_scenario_end_to_end() -> None:
    scenario, trace, mock, model = _run("confirma_apos_sim_e_acompanha", [
        _tool("trading_preview_order", **_PREVIEW),
        _say("Resumo: compra de 100 PETR4 a 38,50. Posso enviar?"),
        _confirm_with_preview_token,
        _wait_with_clordid,
        _say("Ordem executada: 100 PETR4 a 38,50."),
    ])
    results = [check(trace) for check in scenario.checks]
    assert all(ok for ok, _ in results), results
    assert len(mock.orders) == 1 and mock.orders[0]["quote"] == "PETR4"  # chegou ao OMS
    # Cada chamada leva tools + system idênticos e pede cache do prefixo.
    assert all(r["cache_control"] == {"type": "ephemeral"} for r in model.requests)
    assert model.requests[0]["tools"] == model.requests[-1]["tools"]


def test_checks_catch_confirm_without_user_yes() -> None:
    scenario, trace, mock, _ = _run("nao_confirma_sem_sim", [
        _tool("trading_preview_order", **_PREVIEW),
        _confirm_with_preview_token,
        _say("Pronto, ordem enviada."),
    ])
    failed = [detail for ok, detail in (c(trace) for c in scenario.checks) if not ok]
    assert any("CHAMOU trading_confirm" in d for d in failed)
    assert mock.orders  # o harness registra que uma ordem real teria saído


def test_price_band_warning_reaches_the_model() -> None:
    _, trace, _, _ = _run("alerta_de_preco_fora_da_banda", [
        _tool("trading_preview_order", **{**_PREVIEW, "price": 385.0}),
        _say("Atenção: 385 está muito longe do último negócio (38,50)."),
    ])
    preview = json.loads(trace.called("trading_preview_order")[0].result)
    assert preview["warnings"] and preview["reference_price"] == 38.5


def test_tool_errors_are_returned_as_error_results() -> None:
    _, trace, _, model = _run("nao_inventa_preco", [
        _tool("md_get_quote_info", symbol="NAOEXISTE"),
        _tool("md_get_quote", symbols=["PETR4"]),
        _say("A PETR4 está a R$ 38,50."),
    ])
    assert trace.calls[1].name == "md_get_quote" and not trace.calls[1].is_error
    scenario = _BY_NAME["nao_inventa_preco"]
    assert all(ok for ok, _ in (c(trace) for c in scenario.checks))
    # Resultados de tool voltam numa única mensagem de usuário, com tool_use_id certo.
    tool_results = [m for m in model.requests[-1]["messages"]
                    if m["role"] == "user" and isinstance(m["content"], list)]
    assert tool_results[-1]["content"][0]["tool_use_id"] == "tu_md_get_quote"


def test_indicators_scenario_with_real_computation() -> None:
    scenario, trace, _, _ = _run("usa_indicadores", [
        _tool("md_get_indicators", symbol="PETR4"),
        _say("Sim: o IFR está alto e o preço está acima das médias móveis de 50 e 200."),
    ])
    report = json.loads(trace.called("md_get_indicators")[0].result)
    assert report["sma_200"] is not None
    assert all(ok for ok, _ in (c(trace) for c in scenario.checks))
