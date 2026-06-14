"""
Pump Signal Analyzer - Scores each coin from 0 to 100
based on price momentum, volume, buy pressure, breakout & liquidity
"""
import logging
from dataclasses import dataclass, field
from typing import Optional, List, Dict

logger = logging.getLogger(__name__)


@dataclass
class SignalResult:
    """Result of pump signal analysis for a single coin."""
    exchange: str
    symbol: str
    market_type: str
    price: float

    # Price changes
    change_5m: float = 0.0
    change_15m: float = 0.0
    change_1h: float = 0.0
    price_velocity: float = 0.0   # rate of acceleration

    # Volume
    volume_ratio: float = 0.0     # current / average
    volume_24h_usdt: float = 0.0

    # Buy pressure
    buy_ratio: float = 0.0        # 0.0 - 1.0
    buy_volume_usdt: float = 0.0

    # Liquidity
    spread_pct: float = 0.0
    depth_usdt: float = 0.0

    # Breakout
    broke_15m_high: bool = False
    broke_1h_high: bool = False
    high_15m: float = 0.0
    high_1h: float = 0.0

    # Score breakdown
    price_score: float = 0.0
    volume_score: float = 0.0
    buy_pressure_score: float = 0.0
    breakout_score: float = 0.0
    liquidity_score: float = 0.0
    total_score: float = 0.0

    # Flags
    passes_liquidity_filter: bool = True
    score_reasons: List[str] = field(default_factory=list)


class PumpAnalyzer:
    def __init__(self, config: dict):
        self.cfg = config
        self.pm = config.get("price_momentum", {})
        self.vol_cfg = config.get("volume", {})
        self.bp_cfg = config.get("buy_pressure", {})
        self.liq_cfg = config.get("liquidity", {})
        self.brk_cfg = config.get("breakout", {})
        self.scoring = config.get("scoring", {})

    def analyze(
        self,
        ticker: Dict,
        klines_5m: List[Dict],
        klines_15m: List[Dict],
        klines_1h: List[Dict],
        trades: Optional[Dict],
        orderbook: Optional[Dict],
    ) -> Optional[SignalResult]:
        """
        Full pump signal analysis.
        Returns SignalResult or None if coin fails basic filters.
        """
        exchange = ticker["exchange"]
        symbol = ticker["symbol"]
        market_type = ticker["market_type"]
        price = ticker.get("price", 0)
        volume_24h = ticker.get("volume_24h_usdt", 0)

        if price <= 0:
            return None

        # --- Liquidity pre-filter ---
        min_vol = self.cfg.get("scanner", {}).get("min_24h_volume_usdt", 500000)
        if volume_24h < min_vol:
            return None

        result = SignalResult(
            exchange=exchange,
            symbol=symbol,
            market_type=market_type,
            price=price,
            volume_24h_usdt=volume_24h,
        )

        # --- Liquidity score ---
        result.liquidity_score, result.passes_liquidity_filter = self._score_liquidity(
            result, orderbook, volume_24h
        )
        if not result.passes_liquidity_filter:
            return None

        # --- Price momentum score ---
        result.price_score = self._score_price_momentum(result, klines_5m, klines_15m, klines_1h, price)

        # --- Volume spike score ---
        result.volume_score = self._score_volume(result, klines_5m)

        # --- Buy pressure score ---
        result.buy_pressure_score = self._score_buy_pressure(result, trades)

        # --- Breakout score ---
        result.breakout_score = self._score_breakout(result, klines_15m, klines_1h, price)

        # --- Total weighted score ---
        w = self.scoring
        result.total_score = (
            result.price_score * w.get("price_weight", 20) / 100 * 100 +
            result.volume_score * w.get("volume_weight", 30) / 100 * 100 +
            result.buy_pressure_score * w.get("buy_pressure_weight", 20) / 100 * 100 +
            result.breakout_score * w.get("breakout_weight", 20) / 100 * 100 +
            result.liquidity_score * w.get("liquidity_weight", 10) / 100 * 100
        )

        return result

    def _score_price_momentum(self, result: SignalResult, k5m, k15m, k1h, price) -> float:
        """Score 0-1 based on price momentum criteria."""
        score = 0.0
        reasons = []

        # 5-minute change
        if len(k5m) >= 2:
            old_price = k5m[-2]["close"] if len(k5m) > 1 else k5m[0]["open"]
            result.change_5m = ((price - old_price) / old_price) * 100 if old_price > 0 else 0
        elif len(k5m) == 1:
            result.change_5m = ((price - k5m[0]["open"]) / k5m[0]["open"]) * 100

        # 15-minute change
        if len(k15m) >= 2:
            old_15 = k15m[0]["open"] if k15m else price
            result.change_15m = ((price - old_15) / old_15) * 100 if old_15 > 0 else 0
        elif len(k15m) == 1:
            result.change_15m = ((price - k15m[0]["open"]) / k15m[0]["open"]) * 100

        # 1-hour change
        if k1h:
            old_1h = k1h[0]["open"]
            result.change_1h = ((price - old_1h) / old_1h) * 100 if old_1h > 0 else 0

        # Price velocity (acceleration rate)
        if result.change_5m > 0 and result.change_15m > 0:
            result.price_velocity = result.change_5m / max(result.change_15m, 0.01)

        min_5m = self.pm.get("min_change_5m", 2.0)
        min_15m = self.pm.get("min_change_15m", 3.0)
        max_15m = self.pm.get("max_change_15m", 15.0)
        min_1h = self.pm.get("min_change_1h", 5.0)
        max_1h = self.pm.get("max_change_1h", 30.0)

        # Score the 5m change
        if result.change_5m >= min_5m:
            contribution = min(result.change_5m / (min_5m * 3), 1.0) * 0.35
            score += contribution
            reasons.append(f"5m +{result.change_5m:.1f}%")

        # Score the 15m change (must be in range, not already pumped)
        if min_15m <= result.change_15m <= max_15m:
            contribution = min(result.change_15m / (min_15m * 3), 1.0) * 0.35
            score += contribution
            reasons.append(f"15m +{result.change_15m:.1f}%")
        elif result.change_15m > max_15m:
            # Already pumped hard, reduce score
            score -= 0.2

        # Score 1h change
        if min_1h <= result.change_1h <= max_1h:
            contribution = min(result.change_1h / (min_1h * 2), 1.0) * 0.30
            score += contribution
            reasons.append(f"1h +{result.change_1h:.1f}%")

        result.score_reasons.extend(reasons)
        return max(0.0, min(1.0, score))

    def _score_volume(self, result: SignalResult, klines_5m: List[Dict]) -> float:
        """Score 0-1 based on volume spike."""
        if not klines_5m or len(klines_5m) < 3:
            return 0.0

        recent_vols = [c["volume"] for c in klines_5m]
        if not recent_vols:
            return 0.0

        current_vol = recent_vols[-1]
        avg_vol = sum(recent_vols[:-1]) / len(recent_vols[:-1]) if len(recent_vols) > 1 else current_vol

        if avg_vol <= 0:
            return 0.0

        result.volume_ratio = current_vol / avg_vol
        spike_mult = self.vol_cfg.get("spike_multiplier", 3.0)

        if result.volume_ratio >= spike_mult:
            score = min((result.volume_ratio - spike_mult) / spike_mult + 0.7, 1.0)
            result.score_reasons.append(f"Vol x{result.volume_ratio:.1f}")
            return score
        elif result.volume_ratio >= spike_mult * 0.7:
            return 0.4

        return 0.0

    def _score_buy_pressure(self, result: SignalResult, trades: Optional[Dict]) -> float:
        """Score 0-1 based on buy pressure from recent trades."""
        if not trades:
            return 0.3  # Neutral if no data

        result.buy_ratio = trades.get("buy_ratio", 0.5)
        result.buy_volume_usdt = trades.get("buy_volume", 0)

        min_buy_ratio = self.bp_cfg.get("min_buy_ratio", 0.60)
        taker_threshold = self.bp_cfg.get("taker_buy_threshold", 0.65)

        if result.buy_ratio >= taker_threshold:
            score = min((result.buy_ratio - taker_threshold) / 0.2 + 0.7, 1.0)
            result.score_reasons.append(f"Buy {result.buy_ratio*100:.0f}%")
            return score
        elif result.buy_ratio >= min_buy_ratio:
            score = (result.buy_ratio - min_buy_ratio) / (taker_threshold - min_buy_ratio) * 0.5
            result.score_reasons.append(f"Buy {result.buy_ratio*100:.0f}%")
            return score

        return 0.0

    def _score_breakout(self, result: SignalResult, k15m, k1h, price) -> float:
        """Score 0-1 based on breakout detection."""
        score = 0.0
        resistance_pct = self.brk_cfg.get("resistance_break_percent", 0.1)

        # 15-minute high breakout
        if k15m and len(k15m) >= 2:
            lookback = self.brk_cfg.get("lookback_15m_candles", 3)
            relevant = k15m[:-1][-lookback:] if len(k15m) > 1 else []
            if relevant:
                result.high_15m = max(c["high"] for c in relevant)
                if price > result.high_15m * (1 + resistance_pct / 100):
                    result.broke_15m_high = True
                    score += 0.4
                    result.score_reasons.append("Broke 15m high")

        # 1-hour high breakout
        if k1h and len(k1h) >= 2:
            relevant_1h = k1h[:-1][-2:]
            if relevant_1h:
                result.high_1h = max(c["high"] for c in relevant_1h)
                if price > result.high_1h * (1 + resistance_pct / 100):
                    result.broke_1h_high = True
                    score += 0.6
                    result.score_reasons.append("Broke 1h high")

        return min(1.0, score)

    def _score_liquidity(self, result: SignalResult, orderbook: Optional[Dict], volume_24h: float):
        """Score 0-1 for liquidity quality. Returns (score, passes_filter)."""
        max_spread = self.liq_cfg.get("max_spread_percent", 0.5)
        min_depth = self.liq_cfg.get("min_orderbook_depth_usdt", 10000)

        if not orderbook:
            # No orderbook data, use volume as proxy
            if volume_24h > 1_000_000:
                return 0.7, True
            elif volume_24h > 500_000:
                return 0.5, True
            return 0.3, True

        result.spread_pct = orderbook.get("spread_pct", 999)
        result.depth_usdt = orderbook.get("total_depth_usdt", 0)

        # Filter out coins with huge spreads (illiquid/dangerous)
        if result.spread_pct > max_spread:
            return 0.0, False

        if result.depth_usdt < min_depth:
            return 0.0, False

        # Score based on depth
        score = 0.0
        if result.depth_usdt > 100_000:
            score = 1.0
        elif result.depth_usdt > 50_000:
            score = 0.8
        elif result.depth_usdt > 20_000:
            score = 0.6
        else:
            score = 0.4

        # Bonus for tight spread
        if result.spread_pct < 0.1:
            score = min(score + 0.1, 1.0)

        return score, True
