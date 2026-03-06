import os
import time
import json
import logging
from datetime import datetime

import ccxt
import pandas as pd

from ta.trend import PSARIndicator, EMAIndicator, ADXIndicator
from ta.momentum import RSIIndicator

from market_simulator import MarketSimulator
from signal_sender import SignalSender


API_KEY = os.getenv("ASCENDEX_API_KEY", "")
API_SECRET = os.getenv("ASCENDEX_SECRET", "")

RUN_IN_PAPER = True
USE_SIMULATOR = os.getenv("USE_SIMULATOR", "0") == "1"

SYMBOL = "ETH/USDT:USDT"

LEVERAGE = 500
POSITION_PERCENT = 0.10

START_BANK = 100.0

STATE_FILE = "goldantilopaeth500_state.json"


TIMEFRAMES = {
    "1m": 1,
    "5m": 5,
    "30m": 30
}


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

    def get_tf_direction(self, df):

        psar = PSARIndicator(
            high=df["high"],
            low=df["low"],
            close=df["close"],
            step=0.05,
            max_step=0.5
        ).psar()

        price = df["close"].iloc[-1]

        return "long" if price > psar.iloc[-1] else "short"

    def get_ultra_signal(self):

        df = self.fetch_ohlcv_tf("1m")

        if df is None or len(df) < 100:
            return None

        df5 = self.fetch_ohlcv_tf("5m")
        df30 = self.fetch_ohlcv_tf("30m")

        if df5 is None or df30 is None:
            return None

        dir1 = self.get_tf_direction(df)
        dir5 = self.get_tf_direction(df5)
        dir30 = self.get_tf_direction(df30)

        ema20 = EMAIndicator(df["close"], window=20).ema_indicator()
        ema50 = EMAIndicator(df["close"], window=50).ema_indicator()

        rsi = RSIIndicator(df["close"], window=14).rsi()

        adx = ADXIndicator(
            high=df["high"],
            low=df["low"],
            close=df["close"],
            window=14
        ).adx()

        vol_avg = df["volume"].rolling(20).mean()

        price = df["close"].iloc[-1]

        if (
            dir1 == "long"
            and dir5 == "long"
            and dir30 == "long"
            and ema20.iloc[-1] > ema50.iloc[-1]
            and rsi.iloc[-1] > 55
            and adx.iloc[-1] > 18
            and df["volume"].iloc[-1] > vol_avg.iloc[-1]
        ):
            return "long"

        if (
            dir1 == "short"
            and dir5 == "short"
            and dir30 == "short"
            and ema20.iloc[-1] < ema50.iloc[-1]
            and rsi.iloc[-1] < 45
            and adx.iloc[-1] > 18
            and df["volume"].iloc[-1] > vol_avg.iloc[-1]
        ):
            return "short"

        return None

    def get_current_price(self):

        try:

            if USE_SIMULATOR:
                return self.simulator.get_current_price()

            return float(self.exchange.fetch_ticker(SYMBOL)["last"])

        except:
            return 3000.0

    def place_market_order(self, side, amount_base):

        price = self.get_current_price()

        pos_dir = "long" if side == "buy" else "short"

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

        logging.info(f"OPEN {pos_dir}")

    def close_position(self, reason="signal_reverse"):

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
            "close_reason": reason
        }

        state["trades"].insert(0, trade)

        if pos["side"] == "long":
            self.signal_sender.send_close_long()

        else:
            self.signal_sender.send_close_short()

        state["in_position"] = False
        state["position"] = None

        self.save_state_to_file()

    def strategy_loop(self, should_continue=lambda: True):

        logging.info("ULTRA STRATEGY STARTED")

        while should_continue():

            try:

                signal = self.get_ultra_signal()

                if state["in_position"]:

                    if signal and signal != state["position"]["side"]:
                        self.close_position("trend_reverse")

                else:

                    if signal:

                        side = "buy" if signal == "long" else "sell"

                        price = self.get_current_price()

                        notional = state["balance"] * POSITION_PERCENT * LEVERAGE

                        amount = notional / price

                        self.place_market_order(side, amount)

                time.sleep(5)

            except Exception as e:

                logging.error(f"Loop error: {e}")

                time.sleep(10)
