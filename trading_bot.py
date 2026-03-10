import os
import time
import json
import threading
import random
from datetime import datetime, timedelta

import ccxt
import pandas as pd
from ta.trend import PSARIndicator
import logging
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
TIMEFRAMES = {"1m": 1, "5m": 5, "30m": 30}  
MIN_TRADE_SECONDS = 120  
MIN_RANDOM_TRADE_SECONDS = 480  
MAX_RANDOM_TRADE_SECONDS = 780  
PAUSE_BETWEEN_TRADES = 0  
START_BANK = 100.0  # ОБНОВЛЕНО: Стартовый баланс 100
DASHBOARD_MAX = 20

# ========== Глобальные переменные состояния ==========
state = {
    "balance": START_BANK,
    "available": START_BANK,
    "in_position": False,
    "position": None,  
    "last_trade_time": None,
    "last_1m_dir": None,
    "one_min_flip_count": 0,
    "skip_next_signal": False,  
    "trades": []  
}

class TradingBot:
    def __init__(self, telegram_notifier=None):
        self.notifier = telegram_notifier
        self.signal_sender = SignalSender()
        
        if USE_SIMULATOR:
            logging.info("Initializing market simulator")
            self.simulator = MarketSimulator(initial_price=60000, volatility=0.02)
            self.exchange = None
        else:
            logging.info("Initializing ASCENDEX exchange connection")
            self.simulator = None
            self.exchange = ccxt.ascendex({
                "apiKey": API_KEY,
                "secret": API_SECRET,
                "sandbox": False,
                "enableRateLimit": True,
                "options": {
                    "defaultType": "swap",  
                }
            })
            
            if API_KEY and API_SECRET:
                try:
                    if ISOLATED:
                        self.exchange.set_margin_mode('isolated', SYMBOL)
                    self.exchange.set_leverage(LEVERAGE, SYMBOL)
                except Exception as e:
                    logging.error(f"Failed to configure leverage/margin mode: {e}")
        
        self.load_state_from_file()
        
    def save_state_to_file(self):
        try:
            with open("goldantilopaeth500_state.json", "w") as f:
                json.dump(state, f, default=str, indent=2)
        except Exception as e:
            logging.error(f"Save error: {e}")

    def load_state_from_file(self):
        try:
            with open("goldantilopaeth500_state.json", "r") as f:
                data = json.load(f)
                state.update(data)
        except:
            pass

    def now(self):
        return datetime.utcnow()

    def fetch_ohlcv_tf(self, tf: str, limit=200):
        try:
            if USE_SIMULATOR and self.simulator:
                ohlcv = self.simulator.fetch_ohlcv(tf, limit=limit)
            else:
                ohlcv = self.exchange.fetch_ohlcv(SYMBOL, timeframe=tf, limit=limit)
            
            if not ohlcv:
                return None
                
            df = pd.DataFrame(ohlcv)
            df.columns = ["timestamp", "open", "high", "low", "close", "volume"]
            df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms")
            return df
        except Exception as e:
            logging.error(f"Error fetching {tf} ohlcv: {e}")
            return None

    def compute_psar(self, df: pd.DataFrame):
        if df is None or len(df) < 5:
            return None
        try:
            high_series = pd.Series(df["high"].values)
            low_series = pd.Series(df["low"].values)
            close_series = pd.Series(df["close"].values)
            psar_ind = PSARIndicator(high=high_series, low=low_series, close=close_series, step=0.05, max_step=0.5)
            psar = psar_ind.psar()
            return psar
        except Exception as e:
            logging.error(f"PSAR compute error: {e}")
            return None

    def get_direction_from_psar(self, df: pd.DataFrame):
        psar = self.compute_psar(df)
        if psar is None:
            return None
        last_psar = psar.iloc[-1]
        last_close = df["close"].iloc[-1]
        return "long" if last_close > last_psar else "short"

    def get_current_price(self):
        try:
            if USE_SIMULATOR and self.simulator:
                return self.simulator.get_current_price()
            else:
                ticker = self.exchange.fetch_ticker(SYMBOL)
                return float(ticker["last"])
        except Exception as e:
            logging.error(f"fetch ticker error: {e}")
            return float(state["position"]["entry_price"]) if state["position"] else 3000.0

    def place_market_order(self, side: str, amount_base: float):
        logging.info(f"[{self.now()}] PLACE MARKET ORDER -> side={side}, amount={amount_base:.6f}")
        
        # РЕАЛЬНОЕ ИСПОЛНЕНИЕ (даже если RUN_IN_PAPER=False, логика получения цены теперь верная)
        try:
            if not RUN_IN_PAPER and API_KEY:
                # Отправляем реальный ордер
                order = self.exchange.create_market_buy_order(SYMBOL, amount_base) if side == "buy" else self.exchange.create_market_sell_order(SYMBOL, amount_base)
                # ОБНОВЛЕНО: Берем цену исполнения прямо из ответа биржи
                entry_price = float(order.get("average", order.get("price", self.get_current_price())))
            else:
                # Бумажная торговля
                entry_price = self.get_current_price()

            entry_time = datetime.utcnow()
            notional = amount_base * entry_price
            margin = notional / LEVERAGE 
            
            state["available"] -= margin
            close_time_seconds = random.randint(MIN_RANDOM_TRADE_SECONDS, MAX_RANDOM_TRADE_SECONDS)
            
            if "telegram_trade_counter" not in state:
                state["telegram_trade_counter"] = 1
            else:
                state["telegram_trade_counter"] += 1
            trade_number = state["telegram_trade_counter"]
            
            state["in_position"] = True
            state["position"] = {
                "side": "long" if side == "buy" else "short",
                "entry_price": entry_price, # Здесь теперь точная цена с биржи
                "size_base": amount_base,
                "notional": notional,
                "margin": margin,
                "entry_time": entry_time.isoformat(),
                "close_time_seconds": close_time_seconds,
                "trade_number": trade_number
            }
            state["last_trade_time"] = entry_time.isoformat()
            
            if self.notifier:
                self.notifier.send_position_opened(state["position"], entry_price, trade_number, state["balance"])
            
            if state["position"]["side"] == "long":
                self.signal_sender.send_open_long()
            else:
                self.signal_sender.send_open_short()
            
            return state["position"]
        except Exception as e:
            logging.error(f"place_market_order error: {e}")
            return None

    # Остальные методы (close_position, strategy_loop и т.д.) без изменений
