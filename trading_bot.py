import os
import time
import json
import random
from datetime import datetime

import ccxt
import pandas as pd
from ta.trend import PSARIndicator
import logging

from market_simulator import MarketSimulator
from signal_sender import SignalSender

# ========== Конфигурация ==========
API_KEY = os.getenv("ASCENDEX_API_KEY", "")
API_SECRET = os.getenv("ASCENDEX_SECRET", "")
RUN_IN_PAPER = os.getenv("RUN_IN_PAPER", "1") == "1"
USE_SIMULATOR = os.getenv("USE_SIMULATOR", "0") == "1"

SYMBOL = "ETH/USDT:USDT"
LEVERAGE = 500
ISOLATED = True
POSITION_PERCENT = 0.10

TIMEFRAMES = {"1m": 1, "5m": 5, "15m": 15}

MIN_RANDOM_TRADE_SECONDS = 480
MAX_RANDOM_TRADE_SECONDS = 780

START_BANK = 100.0
DASHBOARD_MAX = 20

# ========== STATE ==========
state = {
    "balance": START_BANK,
    "available": START_BANK,
    "in_position": False,
    "position": None,
    "last_trade_time": None,
    "last_1m_dir": None,
    "skip_next_signal": False,
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
                "options": {"defaultType": "swap"},
            })

        self.load_state_from_file()

    # ---------- helpers ----------
    def save_state_to_file(self):
        with open("goldantilopaeth500_state.json", "w") as f:
            json.dump(state, f, indent=2)

    def load_state_from_file(self):
        try:
            with open("goldantilopaeth500_state.json") as f:
                state.update(json.load(f))
        except:
            pass

    def fetch_ohlcv_tf(self, tf, limit=200):
        if USE_SIMULATOR:
            ohlcv = self.simulator.fetch_ohlcv(tf, limit)
        else:
            ohlcv = self.exchange.fetch_ohlcv(SYMBOL, tf, limit=limit)

        df = pd.DataFrame(ohlcv, columns=["ts", "open", "high", "low", "close", "vol"])
        return df

    def get_direction_from_psar(self, df):
        psar = PSARIndicator(
            df["high"], df["low"], df["close"],
            step=0.05, max_step=0.5
        ).psar()
        return "long" if df["close"].iloc[-1] > psar.iloc[-1] else "short"

    def get_price(self):
        if USE_SIMULATOR:
            return self.simulator.get_current_price()
        return self.exchange.fetch_ticker(SYMBOL)["last"]

    # ---------- trading ----------
    def open_position(self, side):
        price = self.get_price()
        notional = state["balance"] * POSITION_PERCENT * LEVERAGE
        size = notional / price

        close_time = random.randint(MIN_RANDOM_TRADE_SECONDS, MAX_RANDOM_TRADE_SECONDS)

        state["position"] = {
            "side": side,
            "entry_price": price,
            "size": size,
            "entry_time": datetime.utcnow().isoformat(),
            "close_time_seconds": close_time,
        }
        state["in_position"] = True

        if side == "long":
            self.signal_sender.send_open_long()
        else:
            self.signal_sender.send_open_short()

        logging.info(f"OPEN {side.upper()} @ {price}")

    def close_position(self, reason):
        side = state["position"]["side"]

        if side == "long":
            self.signal_sender.send_close_long()
        else:
            self.signal_sender.send_close_short()

        logging.info(f"CLOSE {side.upper()} reason={reason}")

        state["in_position"] = False
        state["position"] = None
        state["skip_next_signal"] = True
        self.save_state_to_file()

    # ---------- STRATEGY ----------
    def strategy_loop(self):
        while True:
            try:
                df1 = self.fetch_ohlcv_tf("1m")
                df5 = self.fetch_ohlcv_tf("5m")
                df15 = self.fetch_ohlcv_tf("15m")

                dir_1m = self.get_direction_from_psar(df1)
                dir_5m = self.get_direction_from_psar(df5)
                dir_15m = self.get_direction_from_psar(df15)

                logging.info(f"SAR 1m:{dir_1m} 5m:{dir_5m} 15m:{dir_15m}")

                # ===== CLOSE: смена 5m =====
                if state["in_position"]:
                    entry = datetime.fromisoformat(state["position"]["entry_time"])
                    duration = (datetime.utcnow() - entry).total_seconds()

                    if duration >= state["position"]["close_time_seconds"]:
                        self.close_position("random_time")
                        continue

                    if dir_5m != state["position"]["side"]:
                        self.close_position("sar_5m_change")
                        continue

                # ===== OPEN: совпадение 1m + 5m =====
                else:
                    if state["last_1m_dir"] != dir_1m:
                        state["skip_next_signal"] = False

                    state["last_1m_dir"] = dir_1m

                    if (
                        not state["skip_next_signal"]
                        and dir_1m == dir_5m
                        and dir_1m in ["long", "short"]
                    ):
                        self.open_position(dir_1m)

                time.sleep(5)

            except Exception as e:
                logging.error(e)
                time.sleep(5)
