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
POSITION_PERCENT = 0.10  # 10% от банка
TIMEFRAMES = {"1m": 1, "30m": 30}  
START_BANK = 100.0  

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
                    if data.get("balance") and not np.isnan(data["balance"]):
                        state.update(data)
        except: pass

    def save_state_to_file(self):
        try:
            with open("goldantilopaeth500_state.json", "w") as f:
                json.dump(state, f, indent=2, default=str)
        except: pass

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

    def get_current_directions(self):
        directions = {}
        for tf in TIMEFRAMES.keys():
            df = self.fetch_ohlcv_tf(tf)
            directions[tf] = self.get_direction_from_psar(df)
        return directions

    def place_market_order(self, side, amount_base):
        try:
            if amount_base is None or np.isnan(amount_base) or amount_base <= 0:
                return None

            entry_price = self.get_current_price()
            notional = float(amount_base * entry_price)
            margin_used = notional / LEVERAGE

            state["telegram_trade_counter"] = state.get("telegram_trade_counter", 0) + 1
            state["in_position"] = True
            
            # МГНОВЕННОЕ ОБНОВЛЕНИЕ AVAILABLE (вычитаем маржу)
            state["available"] = round(float(state["balance"] - margin_used), 2)
            
            state["position"] = {
                "side": "long" if side == "buy" else "short",
                "entry_price": entry_price,
                "size_base": float(amount_base),
                "entry_time": datetime.utcnow().isoformat(),
                "trade_number": state["telegram_trade_counter"],
                "notional": round(notional, 2),
                "margin": round(margin_used, 2)
            }
            self.save_state_to_file()
            logging.info(f"🟢 ВХОД: {side.upper()}. Свободно: ${state['available']}")
            return state["position"]
        except Exception as e:
            logging.error(f"Order error: {e}")
            return None

    def close_position(self, close_reason="manual"):
        if not state["in_position"] or not state["position"]:
            return None
        try:
            exit_price = self.get_current_price()
            entry_price = float(state["position"]["entry_price"])
            size = float(state["position"]["size_base"])
            
            pnl = (exit_price - entry_price) * size if state["position"]["side"] == "long" else (entry_price - exit_price) * size
            
            # ОБНОВЛЯЕМ БАЛАНС И ВОЗВРАЩАЕМ МАРЖУ В AVAILABLE
            state["balance"] = round(float(state["balance"] + pnl), 2)
            state["available"] = state["balance"]
            
            trade = {
                "time": datetime.utcnow().isoformat(),
                "side": state["position"]["side"],
                "pnl": round(pnl, 2),
                "exit_price": exit_price,
                "reason": close_reason
            }
            state["trades"].insert(0, trade)
            state["in_position"] = False
            state["position"] = None
            self.save_state_to_file()
            logging.info(f"🔴 ВЫХОД ({close_reason}): PnL: {round(pnl, 2)}. Баланс: ${state['balance']}")
            return trade
        except Exception as e:
            logging.error(f"Close error: {e}")
            return None

    def strategy_loop(self, should_
