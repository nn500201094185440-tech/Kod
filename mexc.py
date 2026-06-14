"""
MEXC Exchange Connector - Spot & Futures
Uses public REST API (no API key needed for market data)
"""
import asyncio
import logging
import aiohttp
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

MEXC_SPOT_URL = "https://api.mexc.com"
MEXC_FUTURES_URL = "https://contract.mexc.com"


class MEXCConnector:
    def __init__(self, session: aiohttp.ClientSession):
        self.session = session
        self.name = "mexc"

    async def _get_spot(self, endpoint: str, params: dict = None) -> Optional[dict]:
        url = f"{MEXC_SPOT_URL}{endpoint}"
        try:
            async with self.session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    return await resp.json()
                logger.warning(f"MEXC Spot HTTP {resp.status} for {endpoint}")
        except asyncio.TimeoutError:
            logger.warning(f"MEXC Spot timeout: {endpoint}")
        except Exception as e:
            logger.error(f"MEXC Spot error: {e}")
        return None

    async def _get_futures(self, endpoint: str, params: dict = None) -> Optional[dict]:
        url = f"{MEXC_FUTURES_URL}{endpoint}"
        try:
            async with self.session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("success") or "data" in data:
                        return data.get("data", data)
                    logger.debug(f"MEXC Futures API error: {data.get('message')}")
        except asyncio.TimeoutError:
            logger.warning(f"MEXC Futures timeout: {endpoint}")
        except Exception as e:
            logger.error(f"MEXC Futures error: {e}")
        return None

    # ------------------------------------------------------------------ SPOT
    async def get_spot_tickers(self) -> List[Dict]:
        """Get all USDT spot tickers."""
        data = await self._get_spot("/api/v3/ticker/24hr")
        if not data:
            return []

        tickers = []
        for t in data:
            symbol = t.get("symbol", "")
            if not symbol.endswith("USDT"):
                continue
            try:
                price = float(t.get("lastPrice", 0))
                if price <= 0:
                    continue
                tickers.append({
                    "exchange": "mexc",
                    "symbol": symbol,
                    "market_type": "spot",
                    "price": price,
                    "price_change_24h_pct": float(t.get("priceChangePercent", 0)),
                    "volume_24h_usdt": float(t.get("quoteVolume", 0)),
                    "high_24h": float(t.get("highPrice", 0)),
                    "low_24h": float(t.get("lowPrice", 0)),
                    "volume_24h": float(t.get("volume", 0)),
                    "bid": float(t.get("bidPrice", 0)),
                    "ask": float(t.get("askPrice", 0)),
                })
            except (ValueError, TypeError):
                continue
        return tickers

    async def get_spot_orderbook(self, symbol: str, limit: int = 20) -> Optional[Dict]:
        """Get order book for spread and depth analysis."""
        data = await self._get_spot("/api/v3/depth", {"symbol": symbol, "limit": limit})
        if not data:
            return None
        bids = data.get("bids", [])
        asks = data.get("asks", [])
        if not bids or not asks:
            return None
        best_bid = float(bids[0][0])
        best_ask = float(asks[0][0])
        spread_pct = ((best_ask - best_bid) / best_bid) * 100 if best_bid > 0 else 999
        bid_depth = sum(float(b[0]) * float(b[1]) for b in bids[:10])
        ask_depth = sum(float(a[0]) * float(a[1]) for a in asks[:10])
        return {
            "bid": best_bid,
            "ask": best_ask,
            "spread_pct": spread_pct,
            "bid_depth_usdt": bid_depth,
            "ask_depth_usdt": ask_depth,
            "total_depth_usdt": bid_depth + ask_depth,
        }

    async def get_spot_klines(self, symbol: str, interval: str = "5m", limit: int = 20) -> List[Dict]:
        """Get candlestick data. interval: '1m','5m','15m','1h'."""
        data = await self._get_spot("/api/v3/klines", {
            "symbol": symbol, "interval": interval, "limit": limit
        })
        if not data:
            return []
        candles = []
        for c in data:
            try:
                candles.append({
                    "timestamp": int(c[0]),
                    "open": float(c[1]),
                    "high": float(c[2]),
                    "low": float(c[3]),
                    "close": float(c[4]),
                    "volume": float(c[5]),
                    "turnover": float(c[7]),
                })
            except (ValueError, IndexError):
                continue
        return sorted(candles, key=lambda x: x["timestamp"])

    async def get_spot_recent_trades(self, symbol: str, limit: int = 100) -> Optional[Dict]:
        """Analyze recent trades for buy pressure."""
        data = await self._get_spot("/api/v3/trades", {"symbol": symbol, "limit": limit})
        if not data:
            return None
        buy_vol = sum(float(t["price"]) * float(t["qty"])
                      for t in data if not t.get("isBuyerMaker", True))
        sell_vol = sum(float(t["price"]) * float(t["qty"])
                       for t in data if t.get("isBuyerMaker", False))
        total_vol = buy_vol + sell_vol
        buy_ratio = (buy_vol / total_vol) if total_vol > 0 else 0.5
        return {
            "buy_volume": buy_vol,
            "sell_volume": sell_vol,
            "total_volume": total_vol,
            "buy_ratio": buy_ratio,
        }

    # --------------------------------------------------------------- FUTURES
    async def get_futures_tickers(self) -> List[Dict]:
        """Get all USDT futures tickers from MEXC."""
        data = await self._get_futures("/api/v1/contract/ticker")
        if not data:
            return []

        # Handle both list and dict response formats
        ticker_list = data if isinstance(data, list) else data.get("data", [])

        tickers = []
        for t in ticker_list:
            symbol = t.get("symbol", "")
            if not ("USDT" in symbol):
                continue
            # Normalize symbol format: BTC_USDT -> BTCUSDT
            normalized = symbol.replace("_", "")
            try:
                price = float(t.get("lastPrice", 0))
                if price <= 0:
                    continue
                tickers.append({
                    "exchange": "mexc",
                    "symbol": normalized,
                    "market_type": "futures",
                    "price": price,
                    "price_change_24h_pct": float(t.get("priceChangePercent", 0)),
                    "volume_24h_usdt": float(t.get("amount24", 0)),
                    "high_24h": float(t.get("high24Price", 0)),
                    "low_24h": float(t.get("low24Price", 0)),
                    "volume_24h": float(t.get("volume24", 0)),
                    "bid": float(t.get("bid1", 0)),
                    "ask": float(t.get("ask1", 0)),
                    "open_interest": float(t.get("holdVol", 0)),
                    "funding_rate": float(t.get("fundingRate", 0)),
                })
            except (ValueError, TypeError):
                continue
        return tickers

    async def get_futures_klines(self, symbol: str, interval: str = "Min5", limit: int = 20) -> List[Dict]:
        """Get futures candlestick data. interval: Min1, Min5, Min15, Min60."""
        mexc_symbol = symbol.replace("USDT", "_USDT")
        data = await self._get_futures("/api/v1/contract/kline", {
            "symbol": mexc_symbol, "interval": interval, "limit": limit
        })
        if not data:
            return []

        candle_data = data if isinstance(data, dict) else {}
        times = candle_data.get("time", [])
        opens = candle_data.get("open", [])
        highs = candle_data.get("high", [])
        lows = candle_data.get("low", [])
        closes = candle_data.get("close", [])
        vols = candle_data.get("vol", [])

        candles = []
        for i in range(len(times)):
            try:
                candles.append({
                    "timestamp": int(times[i]) * 1000,
                    "open": float(opens[i]),
                    "high": float(highs[i]),
                    "low": float(lows[i]),
                    "close": float(closes[i]),
                    "volume": float(vols[i]),
                    "turnover": float(closes[i]) * float(vols[i]),
                })
            except (ValueError, IndexError):
                continue
        return sorted(candles, key=lambda x: x["timestamp"])

    async def get_futures_recent_trades(self, symbol: str, limit: int = 100) -> Optional[Dict]:
        """Analyze recent futures trades."""
        mexc_symbol = symbol.replace("USDT", "_USDT")
        data = await self._get_futures("/api/v1/contract/deals", {
            "symbol": mexc_symbol, "limit": limit
        })
        if not data:
            return None

        trades = data if isinstance(data, list) else data.get("resultList", [])
        # MEXC: side 1 = buy, 2 = sell
        buy_vol = sum(float(t.get("vol", 0)) * float(t.get("price", 0))
                      for t in trades if t.get("takerSide", 0) == 1)
        sell_vol = sum(float(t.get("vol", 0)) * float(t.get("price", 0))
                       for t in trades if t.get("takerSide", 0) == 2)
        total_vol = buy_vol + sell_vol
        buy_ratio = (buy_vol / total_vol) if total_vol > 0 else 0.5
        return {
            "buy_volume": buy_vol,
            "sell_volume": sell_vol,
            "total_volume": total_vol,
            "buy_ratio": buy_ratio,
        }
