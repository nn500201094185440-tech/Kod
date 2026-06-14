"""
Bybit Exchange Connector - Spot & Futures
Uses public REST API (no API key needed for market data)
"""
import asyncio
import logging
import aiohttp
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

BYBIT_BASE_URL = "https://api.bybit.com"


class BybitConnector:
    def __init__(self, session: aiohttp.ClientSession):
        self.session = session
        self.name = "bybit"

    async def _get(self, endpoint: str, params: dict = None) -> Optional[dict]:
        url = f"{BYBIT_BASE_URL}{endpoint}"
        try:
            async with self.session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("retCode") == 0:
                        return data.get("result", {})
                    else:
                        logger.debug(f"Bybit API error: {data.get('retMsg')}")
                else:
                    logger.warning(f"Bybit HTTP {resp.status} for {endpoint}")
        except asyncio.TimeoutError:
            logger.warning(f"Bybit timeout: {endpoint}")
        except Exception as e:
            logger.error(f"Bybit request error: {e}")
        return None

    # ------------------------------------------------------------------ SPOT
    async def get_spot_tickers(self) -> List[Dict]:
        """Get all USDT spot tickers with price, volume, change data."""
        data = await self._get("/v5/market/tickers", {"category": "spot"})
        if not data:
            return []

        tickers = []
        for t in data.get("list", []):
            symbol = t.get("symbol", "")
            if not symbol.endswith("USDT"):
                continue
            try:
                tickers.append({
                    "exchange": "bybit",
                    "symbol": symbol,
                    "market_type": "spot",
                    "price": float(t.get("lastPrice", 0)),
                    "price_change_24h_pct": float(t.get("price24hPcnt", 0)) * 100,
                    "volume_24h_usdt": float(t.get("turnover24h", 0)),
                    "high_24h": float(t.get("highPrice24h", 0)),
                    "low_24h": float(t.get("lowPrice24h", 0)),
                    "volume_24h": float(t.get("volume24h", 0)),
                    "bid": float(t.get("bid1Price", 0)),
                    "ask": float(t.get("ask1Price", 0)),
                })
            except (ValueError, TypeError):
                continue
        return tickers

    async def get_spot_orderbook(self, symbol: str) -> Optional[Dict]:
        """Get order book for spread & depth analysis."""
        data = await self._get("/v5/market/orderbook", {
            "category": "spot", "symbol": symbol, "limit": 20
        })
        if not data:
            return None
        bids = data.get("b", [])
        asks = data.get("a", [])
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

    async def get_spot_klines(self, symbol: str, interval: str = "5", limit: int = 20) -> List[Dict]:
        """Get candlestick data. interval: '1','5','15','60' (minutes)."""
        data = await self._get("/v5/market/kline", {
            "category": "spot", "symbol": symbol,
            "interval": interval, "limit": limit
        })
        if not data:
            return []
        candles = []
        for c in data.get("list", []):
            try:
                candles.append({
                    "timestamp": int(c[0]),
                    "open": float(c[1]),
                    "high": float(c[2]),
                    "low": float(c[3]),
                    "close": float(c[4]),
                    "volume": float(c[5]),
                    "turnover": float(c[6]),
                })
            except (ValueError, IndexError):
                continue
        return sorted(candles, key=lambda x: x["timestamp"])

    async def get_spot_recent_trades(self, symbol: str, limit: int = 100) -> Optional[Dict]:
        """Analyze recent trades for buy/sell pressure."""
        data = await self._get("/v5/market/recent-trade", {
            "category": "spot", "symbol": symbol, "limit": limit
        })
        if not data:
            return None
        trades = data.get("list", [])
        buy_vol = sum(float(t["size"]) * float(t["price"])
                      for t in trades if t.get("side") == "Buy")
        sell_vol = sum(float(t["size"]) * float(t["price"])
                       for t in trades if t.get("side") == "Sell")
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
        """Get all USDT linear futures tickers."""
        data = await self._get("/v5/market/tickers", {"category": "linear"})
        if not data:
            return []
        tickers = []
        for t in data.get("list", []):
            symbol = t.get("symbol", "")
            if not symbol.endswith("USDT"):
                continue
            try:
                tickers.append({
                    "exchange": "bybit",
                    "symbol": symbol,
                    "market_type": "futures",
                    "price": float(t.get("lastPrice", 0)),
                    "price_change_24h_pct": float(t.get("price24hPcnt", 0)) * 100,
                    "volume_24h_usdt": float(t.get("turnover24h", 0)),
                    "high_24h": float(t.get("highPrice24h", 0)),
                    "low_24h": float(t.get("lowPrice24h", 0)),
                    "volume_24h": float(t.get("volume24h", 0)),
                    "bid": float(t.get("bid1Price", 0)),
                    "ask": float(t.get("ask1Price", 0)),
                    "open_interest": float(t.get("openInterest", 0)),
                    "funding_rate": float(t.get("fundingRate", 0)),
                })
            except (ValueError, TypeError):
                continue
        return tickers

    async def get_futures_klines(self, symbol: str, interval: str = "5", limit: int = 20) -> List[Dict]:
        """Get futures candlestick data."""
        data = await self._get("/v5/market/kline", {
            "category": "linear", "symbol": symbol,
            "interval": interval, "limit": limit
        })
        if not data:
            return []
        candles = []
        for c in data.get("list", []):
            try:
                candles.append({
                    "timestamp": int(c[0]),
                    "open": float(c[1]),
                    "high": float(c[2]),
                    "low": float(c[3]),
                    "close": float(c[4]),
                    "volume": float(c[5]),
                    "turnover": float(c[6]),
                })
            except (ValueError, IndexError):
                continue
        return sorted(candles, key=lambda x: x["timestamp"])

    async def get_futures_recent_trades(self, symbol: str, limit: int = 100) -> Optional[Dict]:
        """Analyze recent futures trades for buy/sell pressure."""
        data = await self._get("/v5/market/recent-trade", {
            "category": "linear", "symbol": symbol, "limit": limit
        })
        if not data:
            return None
        trades = data.get("list", [])
        buy_vol = sum(float(t["size"]) * float(t["price"])
                      for t in trades if t.get("side") == "Buy")
        sell_vol = sum(float(t["size"]) * float(t["price"])
                       for t in trades if t.get("side") == "Sell")
        total_vol = buy_vol + sell_vol
        buy_ratio = (buy_vol / total_vol) if total_vol > 0 else 0.5
        return {
            "buy_volume": buy_vol,
            "sell_volume": sell_vol,
            "total_volume": total_vol,
            "buy_ratio": buy_ratio,
        }
