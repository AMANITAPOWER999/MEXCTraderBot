import os
import time
import json
import logging
from datetime import datetime

import ccxt
import pandas as pd
from ta.trend import PSARIndicator
from market_simulator import MarketSimulator
from signal_sender import SignalSender

# ========== Конфигурация ==========
API_KEY = os.getenv("ASCENDEX_API_KEY", "")
API_SECRET = os.getenv("ASCENDEX_SECRET", "")
RUN_IN_PAPER = True
USE_SIMULATOR = os.getenv("USE_SIMULATOR", "0") == "1"

SYMBOL = "ETH/USDT:USDT"
LEVERAGE = 500
ISOLATED = True
POSITION_PERCENT = 0.10

TIMEFRAMES = {
    "1m": 1,
    "5m": 5,
    "30m": 30
}

START_BANK = 100.0
STATE_FILE = "goldantilopaeth500_state.json"

# ========== Глобальное состояние ==========
state = {
    "balance": START_BANK,
    "available": START_BANK,
    "in_position": False,
    "position": None,
    "last_trade_time": None,
    "trades": []
}


class TradingBot:

    def __init__(self, telegram_notifier=None):
        self.notifier = telegram_notifier
        self.signal_sender = SignalSender()

        if USE_SIMULATOR:
            self.simulator = MarketSimulator(initial_price=3000, volatility=0.02)
            self.exchange = None
        else:
            self.simulator = None
            self.exchange = ccxt.ascendex({
                "apiKey": API_KEY,
                "secret": API_SECRET,
                "enableRateLimit": True,
                "options": {"defaultType": "swap"}
            })

        self.load_state_from_file()

    # ===============================
    # STATE
    # ===============================

    def save_state_to_file(self):
        try:
            with open(STATE_FILE, "w") as f:
                json.dump(state, f, default=str, indent=2)
        except Exception as e:
            logging.error(f"Save error: {e}")

    def load_state_from_file(self):
        try:
            if os.path.exists(STATE_FILE):
                with open(STATE_FILE, "r") as f:
                    data = json.load(f)
                    state.update(data)
        except Exception as e:
            logging.error(f"Load error: {e}")

    # ===============================
    # MARKET DATA
    # ===============================

    def fetch_ohlcv_tf(self, tf: str, limit=200):
        try:
            if USE_SIMULATOR and self.simulator:
                ohlcv = self.simulator.fetch_ohlcv(tf, limit=limit)
            else:
                ohlcv = self.exchange.fetch_ohlcv(SYMBOL, timeframe=tf, limit=limit)

            if not ohlcv:
                return None

            df = pd.DataFrame(
                ohlcv,
                columns=["timestamp", "open", "high", "low", "close", "volume"]
            )

            return df

        except Exception as e:
            logging.error(f"Error fetching {tf}: {e}")
            return None

    def get_direction_from_psar(self, df: pd.DataFrame):

        if df is None or len(df) < 5:
            return None

        psar = PSARIndicator(
            high=df["high"],
            low=df["low"],
            close=df["close"],
            step=0.05,
            max_step=0.5
        ).psar()

        return "long" if df["close"].iloc[-1] > psar.iloc[-1] else "short"

    def get_current_directions(self):

        directions = {}

        for tf in TIMEFRAMES.keys():
            df = self.fetch_ohlcv_tf(tf)
            directions[tf] = self.get_direction_from_psar(df)

        return directions

    def get_current_price(self):

        try:
            if USE_SIMULATOR:
                return self.simulator.get_current_price()

            return float(self.exchange.fetch_ticker(SYMBOL)["last"])

        except:
            return 3000.0

    # ===============================
    # ORDERS
    # ===============================

    def place_market_order(self, side: str, amount_base: float):

        price = self.get_current_price()
        pos_dir = "long" if side == "buy" else "short"

        if RUN_IN_PAPER:

            margin = (amount_base * price) / LEVERAGE

            state["available"] -= margin
            state["in_position"] = True

            state["position"] = {
                "side": pos_dir,
                "entry_price": price,
                "size_base": amount_base,
                "notional": amount_base * price,
                "margin": margin,
                "entry_time": datetime.utcnow().isoformat()
            }

            if side == "buy":
                self.signal_sender.send_open_long()
            else:
                self.signal_sender.send_open_short()

            self.save_state_to_file()

            logging.info(f"OPEN {pos_dir.upper()}")

            return state["position"]

    def close_position(self, close_reason="unknown"):

        if not state["in_position"] or not state["position"]:
            return None

        pos = state["position"]
        price = self.get_current_price()

        pnl = (
            (price - pos["entry_price"]) * pos["size_base"]
            if pos["side"] == "long"
            else (pos["entry_price"] - price) * pos["size_base"]
        )

        fee = abs(pos["notional"]) * 0.0003

        pnl_after_fee = pnl - fee

        state["available"] += pos["margin"] + pnl_after_fee
        state["balance"] = state["available"]

        trade = {
            "time": datetime.utcnow().isoformat(),
            "side": pos["side"],
            "pnl": pnl_after_fee,
            "close_reason": close_reason
        }

        if pos["side"] == "long":
            self.signal_sender.send_close_long()
        else:
            self.signal_sender.send_close_short()

        state["trades"].insert(0, trade)

        state["in_position"] = False
        state["position"] = None

        self.save_state_to_file()

        logging.info(f"CLOSE {close_reason}")

        return trade

    # ===============================
    # STRATEGY
    # ===============================

    def strategy_loop(self, should_continue=lambda: True):

        logging.info("Strategy Loop Active (1m + 30m)")

        while should_continue():

            try:

                dirs = self.get_current_directions()

                d1 = dirs.get("1m")
                d5 = dirs.get("5m")
                d30 = dirs.get("30m")

                if not d1 or not d30:
                    time.sleep(5)
                    continue

                # ===== ВЫХОД =====

                if state["in_position"] and state["position"]:

                    if d1 != state["position"]["side"]:
                        self.close_position(close_reason="sar_1m_reversal")

                # ===== ВХОД =====

                elif not state["in_position"]:

                    # СОВПАДЕНИЕ 1m И 30m
                    if d1 == d30:

                        side = "buy" if d1 == "long" else "sell"

                        price = self.get_current_price()

                        notional = state["balance"] * POSITION_PERCENT * LEVERAGE

                        self.place_market_order(side, notional / price)

                time.sleep(15)

            except Exception as e:

                logging.error(f"Loop error: {e}")

                time.sleep(10)
