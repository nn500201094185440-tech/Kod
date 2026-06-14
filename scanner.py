"""
Main Scanner Engine - Orchestrates exchange monitoring, analysis, and alerts
"""
import asyncio
import logging
import time
from typing import Dict, List, Optional, Tuple
import aiohttp

from exchanges.bybit import BybitConnector
from exchanges.mexc import MEXCConnector
from analyzer import PumpAnalyzer, SignalResult
from database import Database
from telegram_bot import TelegramBot

logger = logging.getLogger(__name__)


class PumpScanner:
    def __init__(self, config: dict, db: Database, telegram: TelegramBot):
        self.config = config
        self.db = db
        self.telegram = telegram
        self.analyzer = PumpAnalyzer(config)

        self.scan_interval = config.get("scanner", {}).get("scan_interval_seconds", 10)
        self.min_score = config.get("scoring", {}).get("min_score_to_alert", 75)
        self.cooldown = config.get("telegram", {}).get("alert_cooldown_minutes", 30)
        self.max_coins = config.get("scanner", {}).get("max_coins_per_scan", 200)

        self._running = False
        self._scan_count = 0
        self._alert_count = 0

    async def start(self, session: aiohttp.ClientSession):
        """Start the continuous scanning loop."""
        self._running = True
        bybit = BybitConnector(session)
        mexc = MEXCConnector(session)

        ex_cfg = self.config.get("exchanges", {})

        logger.info("🚀 Pump Scanner started")

        while self._running:
            scan_start = time.time()
            try:
                tasks = []

                # Build exchange/market tasks
                if ex_cfg.get("bybit", {}).get("enabled", True):
                    markets = ex_cfg["bybit"].get("markets", ["spot", "futures"])
                    if "spot" in markets:
                        tasks.append(self._scan_exchange_market(bybit, "spot"))
                    if "futures" in markets:
                        tasks.append(self._scan_exchange_market(bybit, "futures"))

                if ex_cfg.get("mexc", {}).get("enabled", True):
                    markets = ex_cfg["mexc"].get("markets", ["spot", "futures"])
                    if "spot" in markets:
                        tasks.append(self._scan_exchange_market(mexc, "spot"))
                    if "futures" in markets:
                        tasks.append(self._scan_exchange_market(mexc, "futures"))

                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)

                self._scan_count += 1
                scan_duration = time.time() - scan_start

                if self._scan_count % 10 == 0:
                    logger.info(
                        f"Scan #{self._scan_count} completed in {scan_duration:.1f}s | "
                        f"Total alerts sent: {self._alert_count}"
                    )

                # Cleanup old data every 100 scans
                if self._scan_count % 100 == 0:
                    cleanup_hours = self.config.get("database", {}).get("cleanup_hours", 24)
                    await self.db.cleanup_old_data(cleanup_hours)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Scanner error: {e}", exc_info=True)

            # Wait for next scan
            elapsed = time.time() - scan_start
            wait_time = max(0, self.scan_interval - elapsed)
            await asyncio.sleep(wait_time)

    async def stop(self):
        """Stop the scanner."""
        self._running = False
        logger.info("Scanner stopped")

    async def _scan_exchange_market(self, exchange, market_type: str):
        """Scan one exchange + market combination."""
        try:
            # Step 1: Get all tickers
            if market_type == "spot":
                tickers = await exchange.get_spot_tickers()
            else:
                tickers = await exchange.get_futures_tickers()

            if not tickers:
                logger.debug(f"No tickers from {exchange.name} {market_type}")
                return

            # Step 2: Pre-filter by volume (fast filter)
            min_vol = self.config.get("scanner", {}).get("min_24h_volume_usdt", 500000)
            tickers = [t for t in tickers if t.get("volume_24h_usdt", 0) >= min_vol]

            # Step 3: Sort by 24h gain to prioritize movers, limit count
            tickers = sorted(tickers, key=lambda x: x.get("price_change_24h_pct", 0), reverse=True)
            tickers = tickers[:self.max_coins]

            logger.debug(f"Scanning {len(tickers)} coins on {exchange.name} {market_type}")

            # Step 4: Analyze coins concurrently (in batches to avoid rate limits)
            batch_size = 20
            for i in range(0, len(tickers), batch_size):
                batch = tickers[i:i + batch_size]
                tasks = [
                    self._analyze_coin(exchange, ticker, market_type)
                    for ticker in batch
                ]
                results = await asyncio.gather(*tasks, return_exceptions=True)

                for result in results:
                    if isinstance(result, SignalResult) and result is not None:
                        await self._handle_signal(result)

                # Small delay between batches to be API-friendly
                if i + batch_size < len(tickers):
                    await asyncio.sleep(0.5)

        except Exception as e:
            logger.error(f"Error scanning {exchange.name} {market_type}: {e}")

    async def _analyze_coin(self, exchange, ticker: Dict, market_type: str) -> Optional[SignalResult]:
        """Fetch detailed data and analyze a single coin."""
        symbol = ticker["symbol"]
        try:
            # Fetch klines and trade data concurrently
            if market_type == "spot":
                klines_task_5m = exchange.get_spot_klines(symbol, "5", 15)
                klines_task_15m = exchange.get_spot_klines(symbol, "15", 5)
                klines_task_1h = exchange.get_spot_klines(symbol, "60", 3)
                trades_task = exchange.get_spot_recent_trades(symbol, 100)
                ob_task = exchange.get_spot_orderbook(symbol)
            else:
                # Bybit futures uses different interval format
                if exchange.name == "bybit":
                    klines_task_5m = exchange.get_futures_klines(symbol, "5", 15)
                    klines_task_15m = exchange.get_futures_klines(symbol, "15", 5)
                    klines_task_1h = exchange.get_futures_klines(symbol, "60", 3)
                else:
                    klines_task_5m = exchange.get_futures_klines(symbol, "Min5", 15)
                    klines_task_15m = exchange.get_futures_klines(symbol, "Min15", 5)
                    klines_task_1h = exchange.get_futures_klines(symbol, "Min60", 3)
                trades_task = exchange.get_futures_recent_trades(symbol, 100)
                ob_task = asyncio.sleep(0)  # Futures OB not critical

            klines_5m, klines_15m, klines_1h, trades, orderbook = await asyncio.gather(
                klines_task_5m, klines_task_15m, klines_task_1h, trades_task, ob_task,
                return_exceptions=True
            )

            # Handle exceptions from gather
            klines_5m = klines_5m if isinstance(klines_5m, list) else []
            klines_15m = klines_15m if isinstance(klines_15m, list) else []
            klines_1h = klines_1h if isinstance(klines_1h, list) else []
            trades = trades if isinstance(trades, dict) else None
            orderbook = orderbook if isinstance(orderbook, dict) else None

            # Run analysis
            result = self.analyzer.analyze(ticker, klines_5m, klines_15m, klines_1h, trades, orderbook)
            return result

        except Exception as e:
            logger.debug(f"Analysis error for {symbol}: {e}")
            return None

    async def _handle_signal(self, signal: SignalResult):
        """Process a signal that meets the minimum score."""
        if signal.total_score < self.min_score:
            return

        # Check cooldown
        already_alerted = await self.db.was_alert_sent_recently(
            signal.exchange, signal.symbol, signal.market_type, self.cooldown
        )
        if already_alerted:
            logger.debug(f"Cooldown active for {signal.symbol}")
            return

        logger.info(
            f"🚨 PUMP SIGNAL: {signal.exchange.upper()} {signal.symbol} "
            f"[{signal.market_type}] Score: {signal.total_score:.0f}/100 | "
            f"5m:{signal.change_5m:+.1f}% 15m:{signal.change_15m:+.1f}% "
            f"Vol:{signal.volume_ratio:.1f}x Buy:{signal.buy_ratio*100:.0f}%"
        )

        # Send Telegram alert
        success = await self.telegram.send_pump_alert(signal)

        if success:
            await self.db.save_alert(
                signal.exchange, signal.symbol, signal.market_type, signal.total_score
            )
            self._alert_count += 1
