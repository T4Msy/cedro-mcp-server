"""Modelos de resposta, derivados das tabelas de campo das notas de Market Data.

Response models derived from the Market Data notes' field tables. Todos os campos
são opcionais (``extra="allow"``) para tolerar payloads parciais/não documentados —
a doc lista os "principais campos", não necessariamente todos.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict


class _Base(BaseModel):
    """Base tolerante: aceita e preserva campos não modelados."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)


def _parse_candle_time(value: object) -> datetime | None:
    """``timeTrade`` do candleLast/candleDate vem em produção como string legível
    (ex.: ``"Sep 15, 2026 12:00:00 AM"``), não como timestamp numérico — a suposição original
    (``yyyyMMddHHmm`` numérico) nunca tinha sido confirmada contra a API real e quebrava com
    ``float_parsing`` assim que um cliente real chamou a tool. Aceita os dois formatos.
    """
    if value is None or isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        return datetime.strptime(str(int(value)), "%Y%m%d%H%M")
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        for fmt in ("%b %d, %Y %I:%M:%S %p", "%Y%m%d%H%M"):
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                continue
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            return None
    return None


CandleTime = Annotated[datetime | None, BeforeValidator(_parse_candle_time)]


class Quote(_Base):
    """Cotação de ativo — nota `Consulta de cotacao de ativo (quote)`."""

    symbol: str | None = None
    lastTrade: float | None = None
    previous: float | None = None
    change: float | None = None
    changeWeek: float | None = None
    changeMonth: float | None = None
    changeYear: float | None = None
    bid: float | None = None
    ask: float | None = None
    open: float | None = None
    high: float | None = None
    low: float | None = None
    quantity: float | None = None
    quantityLast: float | None = None
    quantityTrades: float | None = None
    volumeAmount: float | None = None
    volumeFinancier: float | None = None
    volumeBid: float | None = None
    volumeAsk: float | None = None
    volumeBetterBid: float | None = None
    volumeBetterAsk: float | None = None
    average: float | None = None
    marketCode: int | None = None
    interest: float | None = None
    situation: float | None = None
    execPrice: float | None = None
    tickSize: int | None = None
    contractMultiplier: float | None = None
    marketCap: float | None = None
    volumeAverageLast20Days: float | None = None
    theoryPrice: float | None = None
    theoryQuantity: float | None = None
    company: str | None = None
    typeOption: str | None = None
    directionOption: str | None = None
    parentSymbol: str | None = None
    securityType: str | None = None
    assetGroupPhase: str | None = None
    timeUpdate: str | None = None
    dateTrade: str | None = None
    timeLastTrade: str | None = None


class QuoteInformation(_Base):
    """Metadados cadastrais de um ativo — nota `quoteinformation`."""

    marketCode: int | None = None
    quotesLotDefault: int | None = None
    quotesQuotationForm: int | None = None
    quotesIsinPaper: str | None = None
    companyName: str | None = None
    segmentName: str | None = None
    typeQuotesCode: int | None = None
    classificationName: str | None = None
    quotesCurrencyDescription: str | None = None
    quotesExpirationDate: str | None = None
    stockOptionsPe: str | None = None
    stockOptionsYear: int | None = None
    quotesSpeak: str | None = None
    securityType: str | None = None


class Market(_Base):
    """Item da lista de mercados — nota `listmarket`."""

    code: str | None = None
    name: str | None = None
    description: str | None = None
    marketDataBase: str | None = None
    isPublic: str | None = None


class Index(_Base):
    """Item da lista de índices — nota `indexlist`."""

    code: str | None = None
    description: str | None = None


class SymbolList(_Base):
    """Lista de códigos (papéis/opções) — notas `companyquotes` e `optionsquote`."""

    quotesDescription: str | None = None


class Candle(_Base):
    """Candle OHLC — notas `candlelast` / `candledate`."""

    symbol: str | None = None
    price: float | None = None
    open: float | None = None
    high: float | None = None
    low: float | None = None
    previous: float | None = None
    quantityTrades: float | None = None
    volumeAmount: float | None = None
    volumeFinancier: float | None = None
    timeTrade: CandleTime = None


class Book(_Base):
    """Livro de ofertas — nota `book/aggregatedbook/minibook`."""

    symbol: str | None = None
    quoteName: str | None = None
    messageError: str | None = None
    compra: list[dict] | None = None
    venda: list[dict] | None = None


class Trade(_Base):
    """Negócio (Times & Trades) — nota `quotetimestrade`."""

    preco: str | None = None
    quantidade: int | None = None
    corretoraComprando: int | None = None
    corretoraVendendo: int | None = None
    bid: float | None = None
    ask: float | None = None
    volumeBid: float | None = None
    volumeAsk: float | None = None
    volumeBetterBid: float | None = None
    volumeBetterAsk: float | None = None
    indicadorNegocio: int | None = None
    date: float | None = None
    identificadorNegocio: str | None = None


class PlayerRankingItem(_Base):
    """Ranking de corretoras por ativo — nota `playerranking`."""

    playerCode: str | None = None
    player: str | None = None
    volumeFinancier: float | None = None
    volumeAmount: float | None = None
    quantityTrades: float | None = None
    formattedVolumeFinancier: float | None = None
    formattedVolumeAmount: float | None = None
    formattedQuantityTrades: float | None = None
    type: str | None = None


class CrossRankingItem(_Base):
    """Cross ranking por corretora — nota `crossranking`."""

    quote: str | None = None
    volumeFinancier: float | None = None
    volumeAmount: float | None = None
    quantityTrades: float | None = None
    formattedVolumeFinancier: float | None = None
    formattedVolumeAmount: float | None = None
    formattedQuantityTrades: float | None = None
    type: str | None = None


class VolumeAtPrice(_Base):
    """Volume por preço — nota `volumeatprice`."""

    values: list[dict] | None = None


class MoverItem(_Base):
    """Item de maiores altas/baixas — notas `highlist` / `falllist`."""

    quote: str | None = None
    price: float | None = None
    value: float | None = None
    date: str | None = None
    volfin: float | None = None
    change: float | None = None
    qtdeNeg: float | None = None


class NewsItem(_Base):
    """Item de notícia — nota `newslast` e correlatas (newsByDate/newsByAgency/newsQuery/...)."""

    code: str | None = None
    title: str | None = None
    agency: str | None = None
    date: str | None = None


class NewsArticle(NewsItem):
    """Corpo completo de uma notícia — nota `newsbycode`."""

    body: str | None = None


class NewsAgency(_Base):
    """Agência de notícias — nota `newsagency`."""

    code: str | None = None
    name: str | None = None
