import os
import time
import json
import random
import logging
from datetime import datetime

import ccxt
import pandas as pd
from ta.trend import PSARIndicator
from signal_sender import SignalSender

# ========== Конфигурация ==========
API_KEY = os.getenv("ASCENDEX_API_KEY", "")
API_SECRET = os.getenv("ASCENDEX_SECRET", "")
RUN_IN_PAPER = True 
SYMBOL = "ETH/USDT:USDT"  
LEVERAGE = 500  
ISOLATED = True  
POSITION_PERCENT = 0.10  
TIMEFRAMES = {"1m": 1, "5m": 5, "30m": 30}  
START_BANK = 100.0  
DASHBOARD_MAX = 20

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
                    state.update(json.load(f))
        except: pass

    def save_state_to_file(self):
        try:
            with open("goldantilopaeth500_state.json", "w") as f:
                json.dump(state, f, indent=2, default=str)
        except: pass

    def get_current_price(self):
        ticker = self.exchange.fetch_ticker(SYMBOL)
        return float(ticker['last'])

    def fetch_ohlcv_tf(self, tf, limit=100):
        ohlcv = self.exchange.fetch_ohlcv(SYMBOL, timeframe=tf, limit=limit)
        return pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])

    def get_direction_from_psar(self, df):
        psar = PSARIndicator(df["high"], df["low"], df["close"], step=0.05, max_step=0.5).psar()
        return "long" if df["close"].iloc[-1] > psar.iloc[-1] else "short"

    def get_current_directions(self):
        directions = {}
        for tf in TIMEFRAMES.keys():
            try:
                df = self.fetch_ohlcv_tf(tf)
                directions[tf] = self.get_direction_from_psar(df)
            except: directions[tf] = None
        return directions

    def place_market_order(self, side, amount_base):
        try:
            if not RUN_IN_PAPER and API_KEY:
                method = self.exchange.create_market_buy_order if side == 'buy' else self.exchange.create_market_sell_order
                order = method(SYMBOL, amount_base)
                entry_price = order.get('average') or order.get('price') or self.get_current_price()
            else:
                entry_price = self.get_current_price()

            state["telegram_trade_counter"] = state.get("telegram_trade_counter", 0) + 1
            state["in_position"] = True
            state["position"] = {
                "side": "long" if side == "buy" else "short",
                "entry_price": entry_price,
                "size_base": amount_base,
                "entry_time": datetime.utcnow().isoformat(),
                "trade_number": state["telegram_trade_counter"],
                "notional": amount_base * entry_price
            }
            self.save_state_to_file()
            return state["position"]
        except Exception as e:
            logging.error(f"Order error: {e}")
            return None

    def close_position(self, close_reason="manual"):
        if not state["in_position"] or not state["position"]:
            return None
        
        try:
            exit_price = self.get_current_price()
            entry_price = state["position"]["entry_price"]
            size = state["position"]["size_base"]
            
            # Расчет PnL (упрощенно для Paper)
            if state["position"]["side"] == "long":
                pnl = (exit_price - entry_price) * size
            else:
                pnl = (entry_price - exit_price) * size
            
            state["balance"] += pnl
            state["available"] = state["balance"]
            
            trade = {
                "time": datetime.utcnow().isoformat(),
                "side": state["position"]["side"],
                "pnl": pnl,
                "exit_price": exit_price
            }
            state["trades"].insert(0, trade)
            state["in_position"] = False
            state["position"] = None
            self.save_state_to_file()
            logging.info(f"Position closed. PnL: {pnl}")
            return trade
        except Exception as e:
            logging.error(f"Close error: {e}")
            return None

    def strategy_loop(self, should_continue=lambda: True):
        """Исправлено: теперь принимает аргумент should_continue"""
        logging.info("🤖 Strategy loop started")
        while should_continue():
            try:
                dirs = self.get_current_directions()
                dir1, dir30 = dirs.get("1m"), dirs.get("30m")

                if not state["in_position"]:
                    if dir1 == dir30 and dir1 is not None:
                        price = self.get_current_price()
                        size = (state["balance"] * POSITION_PERCENT * LEVERAGE) / price
                        self.place_market_order('buy' if dir1 == 'long' else 'sell', size)
                else:
                    # Проверка выхода через 10 минут
                    entry_t = datetime.fromisoformat(state["position"]["entry_time"])
                    if (datetime.utcnow() - entry_t).total_seconds() > 600:
                        self.close_position(close_reason="timeout")
                
                time.sleep(10)
            except Exception as e:
                logging.error(f"Loop error: {e}")
                time.sleep(10)
