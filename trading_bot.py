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

# ========== Конфигурация ==========
API_KEY = os.getenv("ASCENDEX_API_KEY", "")
API_SECRET = os.getenv("ASCENDEX_SECRET", "")
RUN_IN_PAPER = True 
SYMBOL = "ETH/USDT:USDT"  
LEVERAGE = 500  
POSITION_PERCENT = 0.10  
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
                    # Очистка от старых NaN при загрузке
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
        except:
            return 3000.0

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

            # 1. Берем реальную цену входа
            entry_price = self.get_current_price()
            notional = float(amount_base * entry_price)
            
            # 2. Считаем маржу (сколько реально заблокируется денег)
            margin_used = notional / LEVERAGE

            state["telegram_trade_counter"] = state.get("telegram_trade_counter", 0) + 1
            state["in_position"] = True
            
            # 3. ВЫЧИТАЕМ ИЗ AVAILABLE СРАЗУ (для визуала)
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
            logging.info(f"🟢 ВХОД: {side}. Available: ${state['available']}")
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
            
            # Расчет прибыли
            if state["position"]["side"] == "long":
                pnl = (exit_price - entry_price) * size
            else:
                pnl = (entry_price - exit_price) * size
            
            # 4. ОБНОВЛЯЕМ БАЛАНС И ВОЗВРАЩАЕМ В AVAILABLE
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
            logging.info(f"🔴 ЗАКРЫТО: {close_reason}. Баланс: ${state['balance']}")
            return trade
        except Exception as e:
            logging.error(f"Close error: {e}")
            return None

    def strategy_loop(self, should_continue=lambda: True):
        logging.info("🤖 Робот активен: 1m SAR exit enabled")
        while should_continue():
            try:
                dirs = self.get_current_directions()
                dir1, dir30 = dirs.get("1m"), dirs.get("30m")

                if not state["in_position"]:
                    if dir1 == dir30 and dir1 is not None:
                        price = self.get_current_price()
                        # Расчет сайза: 10% от банка с плечом 500
                        raw_size = (state["balance"] * POSITION_PERCENT * LEVERAGE) / price
                        self.place_market_order('buy' if dir1 == 'long' else 'sell', float(raw_size))
                else:
                    entry_t = datetime.fromisoformat(state["position"]["entry_time"])
                    seconds_passed = (datetime.utcnow() - entry_t).total_seconds()
                    current_side = state["position"]["side"]

                    # УСЛОВИЕ ВЫХОДА: Смена 1м SAR или таймаут 10 минут
                    if (dir1 is not None and dir1 != current_side) or seconds_passed > 600:
                        reason = "trend_flip_1m" if seconds_passed <= 600 else "timeout"
                        self.close_position(close_reason=reason)
                
                time.sleep(10)
            except Exception as e:
                logging.error(f"Loop error: {e}")
                time.sleep(10)
