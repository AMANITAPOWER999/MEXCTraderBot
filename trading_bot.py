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


API_KEY = os.getenv("ASCENDEX_API_KEY", "")
API_SECRET = os.getenv("ASCENDEX_SECRET", "")

USE_SIMULATOR = os.getenv("USE_SIMULATOR", "0") == "1"

SYMBOL = "ETH/USDT:USDT"

LEVERAGE = 500
POSITION_PERCENT = 0.10

START_BANK = 100.0

STATE_FILE = "psar_strategy_state.json"


state = {
    "balance": START_BANK,
    "available": START_BANK,
    "in_position": False,
    "position": None,
    "trades": []
}


class TradingBot:

    def __init__(self):

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

    def fetch_ohlcv(self, tf, limit=200):

        try:

            if USE_SIMULATOR:
                ohlcv = self.simulator.fetch_ohlcv(tf, limit=limit)

            else:
                ohlcv = self.exchange.fetch_ohlcv(SYMBOL, timeframe=tf, limit=limit)

            df = pd.DataFrame(
                ohlcv,
                columns=["timestamp", "open", "high", "low", "close", "volume"]
            )

            return df

        except Exception as e:

            logging.error(f"OHLCV error: {e}")
            return None

    def get_psar_direction(self, df):

        psar = PSARIndicator(
            high=df["high"],
            low=df["low"],
            close=df["close"],
            step=0.02,
            max_step=0.2
        ).psar()

        price = df["close"].iloc[-1]

        return "long" if price > psar.iloc[-1] else "short"

    def get_signal(self):

        df1 = self.fetch_ohlcv("1m")
        df15 = self.fetch_ohlcv("15m")

        if df1 is None or df15 is None:
            return None

        dir1 = self.get_psar_direction(df1)
        dir15 = self.get_psar_direction(df15)

        if dir1 == dir15:
            return dir1

        return None

    def get_current_price(self):

        try:

            if USE_SIMULATOR:
                return self.simulator.get_current_price()

            return float(self.exchange.fetch_ticker(SYMBOL)["last"])

        except:
            return 3000

    def open_position(self, side):

        price = self.get_current_price()

        pos_dir = "long" if side == "buy" else "short"

        state["in_position"] = True

        state["position"] = {
            "side": pos_dir,
            "entry_price": price,
            "entry_time": datetime.utcnow().isoformat()
        }

        if side == "buy":
            self.signal_sender.send_open_long()
        else:
            self.signal_sender.send_open_short()

        logging.info(f"OPEN {pos_dir}")

    def close_position(self):

        pos = state["position"]

        if pos["side"] == "long":
            self.signal_sender.send_close_long()
        else:
            self.signal_sender.send_close_short()

        logging.info("CLOSE POSITION")

        state["in_position"] = False
        state["position"] = None

    def strategy_loop(self):

        logging.info("PSAR 1m + 15m STRATEGY STARTED")

        while True:

            try:

                df1 = self.fetch_ohlcv("1m")

                if df1 is None:
                    time.sleep(5)
                    continue

                dir1 = self.get_psar_direction(df1)

                signal = self.get_signal()

                if state["in_position"]:

                    if dir1 != state["position"]["side"]:
                        self.close_position()

                else:

                    if signal:

                        side = "buy" if signal == "long" else "sell"

                        self.open_position(side)

                time.sleep(5)

            except Exception as e:

                logging.error(f"Loop error: {e}")
                time.sleep(10)
