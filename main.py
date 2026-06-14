"""
Telegram Crypto Pump Scanner Bot
=================================
Entry point - loads config, sets up logging, starts the scanner.

Usage:
    python main.py

Requirements:
    pip install aiohttp aiosqlite pyyaml
"""
import asyncio
import logging
import logging.handlers
import os
import signal
import sys
import yaml
import aiohttp

from database import Database
from telegram_bot import TelegramBot
from scanner import PumpScanner


def load_config(path: str = "config.yaml") -> dict:
    """Load and validate configuration file."""
    if not os.path.exists(path):
        print(f"❌ Config file not found: {path}")
        print("   Please copy config.yaml and fill in your Telegram credentials.")
        sys.exit(1)

    with open(path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # Validate required fields
    tg = config.get("telegram", {})
    if tg.get("bot_token") in (None, "", "YOUR_BOT_TOKEN_HERE"):
        print("❌ Please set your Telegram bot_token in config.yaml")
        print("   Get one from @BotFather on Telegram")
        sys.exit(1)
    if tg.get("chat_id") in (None, "", "YOUR_CHAT_ID_HERE"):
        print("❌ Please set your Telegram chat_id in config.yaml")
        print("   Send a message to @userinfobot to get your chat ID")
        sys.exit(1)

    return config


def setup_logging(config: dict):
    """Set up rotating file and console logging."""
    log_cfg = config.get("logging", {})
    level = getattr(logging, log_cfg.get("level", "INFO").upper(), logging.INFO)
    log_file = log_cfg.get("file", "logs/scanner.log")
    max_bytes = log_cfg.get("max_size_mb", 10) * 1024 * 1024
    backup_count = log_cfg.get("backup_count", 3)

    os.makedirs(os.path.dirname(log_file), exist_ok=True)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    console.setLevel(level)

    # Rotating file handler
    file_handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(level)

    # Root logger
    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(console)
    root.addHandler(file_handler)

    # Suppress noisy libraries
    logging.getLogger("aiohttp").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)


async def main():
    print("""
╔═══════════════════════════════════════════╗
║   🚀  Crypto Pump Scanner Bot  🚀         ║
║   Monitoring Bybit & MEXC Markets         ║
╚═══════════════════════════════════════════╝
    """)

    # Load configuration
    config = load_config("config.yaml")
    setup_logging(config)
    logger = logging.getLogger("main")

    # Ensure data directory exists
    db_path = config.get("database", {}).get("path", "data/pump_scanner.db")
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    # Initialize database
    db = Database(db_path)
    await db.initialize()
    logger.info("✅ Database ready")

    # Set up aiohttp session (shared connection pool)
    connector = aiohttp.TCPConnector(
        limit=100,
        limit_per_host=20,
        ttl_dns_cache=300,
        ssl=True
    )

    async with aiohttp.ClientSession(
        connector=connector,
        headers={"User-Agent": "PumpScannerBot/1.0"}
    ) as session:

        # Initialize Telegram bot
        tg_config = config.get("telegram", {})
        telegram = TelegramBot(
            bot_token=tg_config["bot_token"],
            chat_id=str(tg_config["chat_id"]),
            session=session
        )

        # Verify Telegram connection
        logger.info("Verifying Telegram connection...")
        if not await telegram.verify_connection():
            logger.error("❌ Failed to connect to Telegram. Check your bot_token.")
            return

        # Determine active exchanges and markets for startup message
        ex_cfg = config.get("exchanges", {})
        active_exchanges = [
            name for name, cfg in ex_cfg.items() if cfg.get("enabled", True)
        ]
        active_markets = list(set(
            m for cfg in ex_cfg.values()
            for m in cfg.get("markets", ["spot"])
            if cfg.get("enabled", True)
        ))

        await telegram.send_startup_message(active_exchanges, active_markets)

        # Create and start scanner
        scanner = PumpScanner(config, db, telegram)

        # Graceful shutdown handler
        loop = asyncio.get_event_loop()
        shutdown_event = asyncio.Event()

        def signal_handler():
            logger.info("Shutdown signal received...")
            shutdown_event.set()

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, signal_handler)
            except (NotImplementedError, RuntimeError):
                # Windows doesn't support add_signal_handler
                pass

        # Start scanning in background
        scan_task = asyncio.create_task(scanner.start(session))

        logger.info("✅ Scanner is running. Press Ctrl+C to stop.")

        # Wait until shutdown signal
        try:
            await asyncio.gather(scan_task, shutdown_event.wait())
        except asyncio.CancelledError:
            pass
        except KeyboardInterrupt:
            pass
        finally:
            await scanner.stop()
            scan_task.cancel()
            try:
                await scan_task
            except asyncio.CancelledError:
                pass
            logger.info("👋 Pump Scanner Bot stopped cleanly.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Bot stopped by user.")
