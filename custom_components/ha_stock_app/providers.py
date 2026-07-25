from __future__ import annotations

import abc
import logging
import re
from dataclasses import dataclass, field
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

SYMBOL_PATTERN = re.compile(r"^[A-Z0-9.\-]{1,10}$")

# Keep well under the aiohttp default (5 minutes) so a hung request can't
# stall a poll cycle or leave the config flow spinning.
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=15)


@dataclass
class StockQuote:
    symbol: str
    current_price: float
    previous_close: float
    high: float
    low: float
    open_price: float
    change: float = field(init=False)
    change_percent: float = field(init=False)

    def __post_init__(self) -> None:
        self.change = self.current_price - self.previous_close
        if self.previous_close:
            self.change_percent = (self.change / self.previous_close) * 100
        else:
            self.change_percent = 0.0


def validate_symbols(symbols: list[str]) -> list[str]:
    return [s for s in symbols if not SYMBOL_PATTERN.match(s)]


class StockProvider(abc.ABC):
    @abc.abstractmethod
    async def get_quote(self, symbol: str) -> StockQuote | None: ...

    @abc.abstractmethod
    async def validate_api_key(self) -> bool: ...

    async def get_quotes(self, symbols: list[str]) -> dict[str, StockQuote]:
        results: dict[str, StockQuote] = {}
        for symbol in symbols:
            quote = await self.get_quote(symbol)
            if quote:
                results[symbol] = quote
        return results


class FinnhubProvider(StockProvider):
    BASE_URL = "https://finnhub.io/api/v1"

    def __init__(self, api_key: str, session: aiohttp.ClientSession) -> None:
        self._api_key = api_key
        self._session = session

    async def validate_api_key(self) -> bool:
        try:
            quote = await self.get_quote("AAPL")
            return quote is not None
        except Exception as exc:
            _LOGGER.warning("API key validation failed: %s", type(exc).__name__)
            return False

    async def get_quote(self, symbol: str) -> StockQuote | None:
        if self._session is None or self._session.closed:
            _LOGGER.error("HTTP session not available for Finnhub API")
            return None
        url = f"{self.BASE_URL}/quote"
        params = {"symbol": symbol.upper()}
        headers = {"X-Finnhub-Token": self._api_key}
        try:
            async with self._session.get(
                url, params=params, headers=headers, timeout=REQUEST_TIMEOUT
            ) as resp:
                if resp.status != 200:
                    _LOGGER.error("Finnhub API error %s for %s", resp.status, symbol)
                    return None
                data: dict[str, Any] = await resp.json()
                if not data or data.get("c", 0) == 0:
                    _LOGGER.warning("Finnhub returned no data for %s", symbol)
                    return None
                return StockQuote(
                    symbol=symbol.upper(),
                    current_price=float(data["c"]),
                    previous_close=float(data["pc"]),
                    high=float(data["h"]),
                    low=float(data["l"]),
                    open_price=float(data["o"]),
                )
        # A total-request timeout surfaces as TimeoutError, which is not an
        # aiohttp.ClientError, so it needs to be caught explicitly.
        except (aiohttp.ClientError, TimeoutError, KeyError, ValueError) as exc:
            _LOGGER.error("Finnhub fetch failed for %s: %s", symbol, type(exc).__name__)
            return None


def get_provider(provider_name: str, api_key: str, session: aiohttp.ClientSession) -> StockProvider:
    providers = {
        "finnhub": FinnhubProvider,
    }
    cls = providers.get(provider_name)
    if cls is None:
        raise ValueError(f"Unknown stock provider: {provider_name}")
    return cls(api_key, session)
