import os
import time
import json
import logging
from datetime import datetime

import ccxt
import pandas as pd
import numpy as np
from ta.trend import PSARIndicator
from signal_sender import SignalSender

# ========== КОНФИГУРАЦИЯ ==========
API_KEY = os.getenv("ASCENDEX_API_KEY", "")
API_SECRET = os.getenv("ASCENDEX_SECRET", "")
RUN_IN_PAPER = True 
SYMBOL = "ETH/USDT:USDT"  
LEVERAGE = 500  
POSITION_PERCENT = 0.10  
TIMEFRAMES = {"1m": 1, "30m": 30}  
START_BANK = 100.0  

# Глобальное состояние (единый источник правды для app.py)
state = {
    "balance": START_BANK,
    "available": START_BANK,
    "in_position": False,
    "position": None,
    "trades": [],
    "telegram_trade_counter": 0
}

class TradingBot:
    def __init__(self, telegram_notifier=None):
        self.notifier = telegram_notifier
        self.signal_sender = SignalSender()
        self.exchange = ccxt.ascendex({
            "apiKey": API_KEY,
            "secret": API_SECRET,
            "enableRateLimit": True,
            "options": {"defaultType": "swap"}
        })
        self.load_state_from_file()

    def load_state_from_file(self):
        try:
            if os.path.exists("goldantilopaeth500_state.json"):
                with open("goldantilopaeth500_state.json", "r") as f:
                    data = json.load(f)
                    if "trades" in data:
                        state["trades"] = data["trades"]
                    if data.get("balance") and not np.isnan(data["balance"]):
                        state["balance"] = float(data["balance"])
                        state["available"] = float(data.get("available", data["balance"]))
                        state["telegram_trade_counter"] = data.get("telegram_trade_counter", 0)
                    logging.info(f"✅ Данные загружены. Сделок в истории: {len(state['trades'])}")
        except Exception as e:
            logging.error(f"Ошибка загрузки файла: {e}")

    def save_state_to_file(self):
        try:
            with open("goldantilopaeth500_state.json", "w") as f:
                json.dump(state, f, indent=2, default=str)
        except Exception as e:
            logging.error(f"Ошибка сохранения файла: {e}")

    def get_current_price(self, price_type='last'):
        try:
            ticker = self.exchange.fetch_ticker(SYMBOL)
            price = ticker.get(price_type, ticker.get('last'))
            return float(price) if price else 3000.0
        except: return 3000.0

    def fetch_ohlcv_tf(self, tf, limit=100):
        try:
            ohlcv = self.exchange.fetch_ohlcv(SYMBOL, timeframe=tf, limit=limit)
            return pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
        except: return None

    def get_direction_from_psar(self, df):
        if df is None or len(df) < 10: return None
        psar = PSARIndicator(df["high"], df["low"], df["close"], step=0.05, max_step=0.5).psar()
        last_close = df["close"].iloc[-1]
        last_psar = psar.iloc[-1]
        if np.isnan(last_psar): return None
        return "long" if last_close > last_psar else "short"

    def place_market_order(self, side, amount_base):
        try:
            if amount_base is None or np.isnan(amount_base) or amount_base <= 0:
                return None

            entry
