"""
Database module - SQLite storage for price history and alerts
"""
import aiosqlite
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._lock = asyncio.Lock()

    async def initialize(self):
        """Create tables if they don't exist."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS price_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    exchange TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    market_type TEXT NOT NULL,
                    price REAL NOT NULL,
                    volume REAL,
                    buy_volume REAL,
                    sell_volume REAL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_price_history_symbol_time
                ON price_history(exchange, symbol, timestamp)
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS alerts_sent (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    exchange TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    market_type TEXT NOT NULL,
                    score REAL NOT NULL,
                    sent_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS volume_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    exchange TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    market_type TEXT NOT NULL,
                    volume REAL NOT NULL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await db.commit()
        logger.info("Database initialized successfully")

    async def save_price(self, exchange: str, symbol: str, market_type: str,
                         price: float, volume: float = None,
                         buy_volume: float = None, sell_volume: float = None):
        """Save a price data point."""
        async with self._lock:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("""
                    INSERT INTO price_history
                    (exchange, symbol, market_type, price, volume, buy_volume, sell_volume)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (exchange, symbol, market_type, price, volume, buy_volume, sell_volume))
                await db.commit()

    async def save_prices_bulk(self, records: List[Dict]):
        """Bulk insert price records for efficiency."""
        if not records:
            return
        async with self._lock:
            async with aiosqlite.connect(self.db_path) as db:
                await db.executemany("""
                    INSERT INTO price_history
                    (exchange, symbol, market_type, price, volume, buy_volume, sell_volume)
                    VALUES (:exchange, :symbol, :market_type, :price, :volume, :buy_volume, :sell_volume)
                """, records)
                await db.commit()

    async def get_price_history(self, exchange: str, symbol: str,
                                 market_type: str, minutes: int) -> List[Dict]:
        """Get price history for a symbol within the last N minutes."""
        since = datetime.utcnow() - timedelta(minutes=minutes)
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT price, volume, buy_volume, sell_volume, timestamp
                FROM price_history
                WHERE exchange = ? AND symbol = ? AND market_type = ?
                  AND timestamp >= ?
                ORDER BY timestamp ASC
            """, (exchange, symbol, market_type, since.isoformat())) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    async def get_price_at(self, exchange: str, symbol: str,
                            market_type: str, minutes_ago: int) -> Optional[float]:
        """Get the price N minutes ago (closest record)."""
        target_time = datetime.utcnow() - timedelta(minutes=minutes_ago)
        since = target_time - timedelta(minutes=2)
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("""
                SELECT price FROM price_history
                WHERE exchange = ? AND symbol = ? AND market_type = ?
                  AND timestamp BETWEEN ? AND ?
                ORDER BY ABS(strftime('%s', timestamp) - strftime('%s', ?))
                LIMIT 1
            """, (exchange, symbol, market_type,
                  since.isoformat(), target_time.isoformat(),
                  target_time.isoformat())) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else None

    async def get_volume_average(self, exchange: str, symbol: str,
                                  market_type: str, periods: int = 12) -> Optional[float]:
        """Get average volume over last N 5-minute periods (1 hour)."""
        since = datetime.utcnow() - timedelta(minutes=periods * 5)
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("""
                SELECT AVG(volume) FROM price_history
                WHERE exchange = ? AND symbol = ? AND market_type = ?
                  AND timestamp >= ? AND volume IS NOT NULL
            """, (exchange, symbol, market_type, since.isoformat())) as cursor:
                row = await cursor.fetchone()
                return row[0] if row and row[0] else None

    async def was_alert_sent_recently(self, exchange: str, symbol: str,
                                       market_type: str, cooldown_minutes: int) -> bool:
        """Check if an alert was already sent for this coin recently."""
        since = datetime.utcnow() - timedelta(minutes=cooldown_minutes)
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("""
                SELECT COUNT(*) FROM alerts_sent
                WHERE exchange = ? AND symbol = ? AND market_type = ?
                  AND sent_at >= ?
            """, (exchange, symbol, market_type, since.isoformat())) as cursor:
                row = await cursor.fetchone()
                return row[0] > 0 if row else False

    async def save_alert(self, exchange: str, symbol: str,
                          market_type: str, score: float):
        """Record that an alert was sent."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO alerts_sent (exchange, symbol, market_type, score)
                VALUES (?, ?, ?, ?)
            """, (exchange, symbol, market_type, score))
            await db.commit()

    async def cleanup_old_data(self, hours: int = 24):
        """Delete price data older than N hours."""
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        async with self._lock:
            async with aiosqlite.connect(self.db_path) as db:
                result = await db.execute("""
                    DELETE FROM price_history WHERE timestamp < ?
                """, (cutoff.isoformat(),))
                await db.execute("""
                    DELETE FROM alerts_sent WHERE sent_at < ?
                """, (cutoff.isoformat(),))
                await db.commit()
                logger.info(f"Cleaned up {result.rowcount} old price records")
