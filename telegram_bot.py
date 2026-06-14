"""
Telegram Bot - Sends pump alert notifications
"""
import asyncio
import logging
import aiohttp
from typing import Optional
from analyzer import SignalResult

logger = logging.getLogger(__name__)


class TelegramBot:
    def __init__(self, bot_token: str, chat_id: str, session: aiohttp.ClientSession):
        self.bot_token = bot_token
        self.chat_id = str(chat_id)
        self.session = session
        self.base_url = f"https://api.telegram.org/bot{bot_token}"
        self._semaphore = asyncio.Semaphore(3)  # Max 3 concurrent sends

    async def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        """Send a message to the configured chat."""
        async with self._semaphore:
            try:
                async with self.session.post(
                    f"{self.base_url}/sendMessage",
                    json={
                        "chat_id": self.chat_id,
                        "text": text,
                        "parse_mode": parse_mode,
                        "disable_web_page_preview": True,
                    },
                    timeout=aiohttp.ClientTimeout(total=15)
                ) as resp:
                    data = await resp.json()
                    if data.get("ok"):
                        return True
                    logger.error(f"Telegram error: {data.get('description')}")
            except Exception as e:
                logger.error(f"Telegram send error: {e}")
            return False

    async def send_pump_alert(self, signal: SignalResult) -> bool:
        """Format and send a pump alert."""
        score_bar = self._score_bar(signal.total_score)
        market_emoji = "📈" if signal.market_type == "spot" else "📊"
        exchange_emoji = "🟡" if signal.exchange == "bybit" else "🔵"

        # Format the coin name nicely
        base = signal.symbol.replace("USDT", "")

        # Build change strings
        change_5m_str = f"+{signal.change_5m:.2f}%" if signal.change_5m > 0 else f"{signal.change_5m:.2f}%"
        change_15m_str = f"+{signal.change_15m:.2f}%" if signal.change_15m > 0 else f"{signal.change_15m:.2f}%"
        change_1h_str = f"+{signal.change_1h:.2f}%" if signal.change_1h > 0 else f"{signal.change_1h:.2f}%"

        # Volume ratio string
        vol_str = f"+{(signal.volume_ratio - 1) * 100:.0f}%" if signal.volume_ratio > 1 else "N/A"

        # Volume 24h formatting
        vol_24h = signal.volume_24h_usdt
        if vol_24h >= 1_000_000:
            vol_24h_str = f"${vol_24h/1_000_000:.1f}M"
        elif vol_24h >= 1_000:
            vol_24h_str = f"${vol_24h/1_000:.0f}K"
        else:
            vol_24h_str = f"${vol_24h:.0f}"

        # Breakout indicators
        breakout_str = ""
        if signal.broke_1h_high:
            breakout_str = "🔓 Broke 1H High"
        elif signal.broke_15m_high:
            breakout_str = "🔓 Broke 15M High"

        # Reasons
        reasons_str = " • ".join(signal.score_reasons[:4]) if signal.score_reasons else "Multiple signals"

        message = (
            f"🚀 <b>Possible Pump Alert!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"{exchange_emoji} <b>{signal.exchange.upper()}</b>  {market_emoji} {signal.market_type.upper()}\n\n"
            f"🪙 <b>Coin:</b> <code>{base}/USDT</code>\n"
            f"💰 <b>Price:</b> <code>${signal.price:.8g}</code>\n\n"
            f"📉 <b>Price Change:</b>\n"
            f"  ├ 5m:  <b>{change_5m_str}</b>\n"
            f"  ├ 15m: <b>{change_15m_str}</b>\n"
            f"  └ 1h:  <b>{change_1h_str}</b>\n\n"
            f"📦 <b>Volume Spike:</b> <b>{vol_str}</b>\n"
            f"💚 <b>Buy Pressure:</b> <b>{signal.buy_ratio*100:.0f}%</b>\n"
            f"💧 <b>24h Volume:</b> {vol_24h_str}\n"
        )

        if breakout_str:
            message += f"🔔 <b>Breakout:</b> {breakout_str}\n"

        message += (
            f"\n<b>📊 Signal Score: {signal.total_score:.0f}/100</b>\n"
            f"{score_bar}\n\n"
            f"💡 <i>{reasons_str}</i>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"⚠️ <i>Not financial advice. DYOR.</i>"
        )

        return await self.send_message(message)

    async def send_startup_message(self, exchanges: list, markets: list):
        """Send a startup notification."""
        msg = (
            f"✅ <b>Pump Scanner Bot Started</b>\n\n"
            f"📡 <b>Monitoring:</b> {', '.join(e.upper() for e in exchanges)}\n"
            f"🏪 <b>Markets:</b> {', '.join(markets)}\n"
            f"🎯 <b>Min Score:</b> 75/100\n\n"
            f"<i>Scanning for pump signals...</i>"
        )
        await self.send_message(msg)

    async def send_error_alert(self, error_msg: str):
        """Send an error notification."""
        msg = f"⚠️ <b>Scanner Error</b>\n\n<code>{error_msg[:500]}</code>"
        await self.send_message(msg)

    async def verify_connection(self) -> bool:
        """Verify the bot token and chat_id are valid."""
        try:
            async with self.session.get(
                f"{self.base_url}/getMe",
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                data = await resp.json()
                if data.get("ok"):
                    bot_name = data["result"]["username"]
                    logger.info(f"Telegram bot verified: @{bot_name}")
                    return True
                logger.error(f"Bot token invalid: {data}")
        except Exception as e:
            logger.error(f"Telegram connection error: {e}")
        return False

    @staticmethod
    def _score_bar(score: float) -> str:
        """Visual progress bar for the score."""
        filled = int(score / 10)
        empty = 10 - filled
        if score >= 85:
            emoji = "🔴"
        elif score >= 75:
            emoji = "🟠"
        else:
            emoji = "🟡"
        return f"{emoji} [{'█' * filled}{'░' * empty}] {score:.0f}/100"
