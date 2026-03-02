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

SYMBOL = "ETH/USDT:USDT"  # Инструмент
LEVERAGE = 500            # Плечо x500
ISOLATED = True           # Изолированная маржа
POSITION_PERCENT = 0.10   # 10% от баланса
TIMEFRAMES = {"1m": 1, "5m": 5, "30m": 30} # 15м заменено на 30м
MIN_RANDOM_TRADE_SECONDS = 480
MAX_RANDOM_TRADE_SECONDS = 780
START_BANK = 100.0
DASHBOARD_MAX = 20

# ========== Глобальные переменные состояния ==========
state = {
    "balance": START_BANK,
    "available": START_BANK,
    "in_position": False,
    "position": None,  # dict: {side, entry_price, size_base, entry_time}
    "last_trade_time": None,
    "trades": []
}

class TradingBot:
    def __init__(self, telegram_notifier=None):
        self.notifier = telegram_notifier
        self.signal_sender = SignalSender()
        
        if USE_SIMULATOR:
            logging.info("Initializing market simulator")
            self.simulator = MarketSimulator(initial_price=3000, volatility=0.02)
            self.exchange = None
        else:
            logging.info("Initializing ASCENDEX exchange connection")
            self.simulator = None
            self.exchange = ccxt.ascendex({
                "apiKey": API_KEY,
                "secret": API_SECRET,
                "enableRateLimit": True,
                "options": {"defaultType": "swap"}
            })
            
            if API_KEY and API_SECRET:
                try:
                    if ISOLATED:
                        self.exchange.set_margin_mode('isolated', SYMBOL)
                    self.exchange.set_leverage(LEVERAGE, SYMBOL)
                except Exception as e:
                    logging.error(f"Failed to configure leverage/margin: {e}")
        
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
            
            if not ohlcv: return None
            df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
            df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms")
            return df
        except Exception as e:
            logging.error(f"Error fetching {tf} ohlcv: {e}")
            return None

    def compute_psar(self, df: pd.DataFrame):
        if df is None or len(df) < 5: return None
        try:
            psar_ind = PSARIndicator(high=df["high"], low=df["low"], close=df["close"], step=0.05, max_step=0.5)
            return psar_ind.psar()
        except Exception as e:
            logging.error(f"PSAR compute error: {e}")
            return None

    def get_direction_from_psar(self, df: pd.DataFrame):
        psar = self.compute_psar(df)
        if psar is None: return None
        return "long" if df["close"].iloc[-1] > psar.iloc[-1] else "short"

    def compute_order_size_usdt(self, balance, price):
        notional = balance * POSITION_PERCENT * LEVERAGE
        base_amount = notional / price
        return base_amount, notional

    def place_market_order(self, side: str, amount_base: float):
        logging.info(f"[{self.now()}] OPENING {side.upper()} amount={amount_base:.6f}")
        price = self.get_current_price()
        
        if RUN_IN_PAPER:
            entry_time = datetime.utcnow()
            margin = (amount_base * price) / LEVERAGE
            state["available"] -= margin
            state["in_position"] = True
            state["position"] = {
                "side": "long" if side == "buy" else "short",
                "entry_price": price,
                "size_base": amount_base,
                "notional": amount_base * price,
                "margin": margin,
                "entry_time": entry_time.isoformat()
            }
            # Отправка сигнала
            if side == "buy": self.signal_sender.send_open_long()
            else: self.signal_sender.send_open_short()
            
            if self.notifier:
                self.notifier.send_position_opened(state["position"], price, len(state["trades"])+1, state["balance"])
            return state["position"]
        return None

    def close_position(self, close_reason="unknown"):
        if not state["in_position"]: return None
        pos = state["position"]
        price = self.get_current_price()
        
        if RUN_IN_PAPER:
            pnl = (price - pos["entry_price"]) * pos["size_base"] if pos["side"] == "long" else (pos["entry_price"] - price) * pos["size_base"]
            fee = abs(pos["notional"]) * 0.0003
            pnl_after_fee = pnl - fee
            
            state["available"] += pos["margin"] + pnl_after_fee
            state["balance"] = state["available"]
            
            trade = {
                "time": datetime.utcnow().isoformat(),
                "side": pos["side"],
                "entry_price": pos["entry_price"],
                "exit_price": price,
                "pnl": pnl_after_fee,
                "close_reason": close_reason
            }
            
            if pos["side"] == "long": self.signal_sender.send_close_long()
            else: self.signal_sender.send_close_short()
            
            if self.notifier:
                self.notifier.send_position_closed(trade, len(state["trades"]), state["balance"])
                
            state["trades"].insert(0, trade)
            state["in_position"] = False
            state["position"] = None
            self.save_state_to_file()
            return trade

    def get_current_price(self):
        try:
            if USE_SIMULATOR: return self.simulator.get_current_price()
            ticker = self.exchange.fetch_ticker(SYMBOL)
            return float(ticker["last"])
        except: return 3000.0

    def strategy_loop(self, should_continue=lambda: True):
        logging.info(f"Strategy Loop Started. Filter: Entry(1m+30m), Exit(1m Change)")
        
        while should_continue():
            try:
                dirs = {}
                for tf in ["1m", "5m", "30m"]:
                    df = self.fetch_ohlcv_tf(tf)
                    dirs[tf] = self.get_direction_from_psar(df) if df is not None else None

                if dirs["1m"] is None or dirs["30m"] is None:
                    time.sleep(5)
                    continue

                dir_1m, dir_30m = dirs["1m"], dirs["30m"]
                logging.info(f"[{self.now()}] PSAR: 1m:{dir_1m} | 5m:{dirs['5m']} | 30m:{dir_30m}")

                # --- ЛОГИКА ---
                if state["in_position"]:
                    # Выход: если 1m SAR сменил направление
                    if dir_1m != state["position"]["side"]:
                        logging.info(f"⚠️ EXIT SIGNAL: 1m changed to {dir_1m}")
                        self.close_position(close_reason="sar_1m_reversal")
                else:
                    # Вход: если 1m и 30m совпадают
                    if dir_1m == dir_30m:
                        logging.info(f"🚀 ENTRY SIGNAL: 1m & 30m match ({dir_1m})")
                        side = "buy" if dir_1m == "long" else "sell"
                        size_base, _ = self.compute_order_size_usdt(state["balance"], self.get_current_price())
                        self.place_market_order(side, size_base)
                        self.save_state_to_file()

                time.sleep(10)
            except Exception as e:
                logging.error(f"Loop error: {e}")
                time.sleep(5)
