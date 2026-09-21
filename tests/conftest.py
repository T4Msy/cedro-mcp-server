"""Fixtures de teste: Settings de teste e um CedroClient com httpx mockável.

Test fixtures: test Settings and a CedroClient with a mockable httpx client.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from cedro_mcp.client import CedroClient
from cedro_mcp.config import Settings

FIXTURES = Path(__file__).parent / "fixtures"
BASE_URL = "https://webfeeder.cedrotech.com"


def load_fixture(name: str) -> object:
    """Carrega um JSON de tests/fixtures."""
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def settings() -> Settings:
    return Settings(
        base_url=BASE_URL,
        user="tester",
        password="secret",
        news_client_id="cid",
        news_client_secret="csecret",
        docs_path=Path(__file__).parent,
        http_timeout=5.0,
        # stdio: os testes só verificam registro de tools/resources, nunca sobem um servidor
        # HTTP de verdade — em streamable-http sem auth, build_server() agora recusaria montar
        # (ver ConfigurationError), o que é o comportamento certo pra produção, não pra este
        # fixture.
        transport="stdio",
    )


@pytest.fixture
def client(settings: Settings) -> CedroClient:
    """CedroClient usando um httpx.Client real (interceptado pelo respx)."""
    http = httpx.Client(base_url=settings.base_url, timeout=settings.http_timeout)
    cedro = CedroClient(settings, http=http)
    yield cedro
    cedro.close()
