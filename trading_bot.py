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

SYMBOL = "ETH/USDT:USDT"  # инструмент
LEVERAGE = 500  # плечо x500
ISOLATED = True  # изолированная маржа
POSITION_PERCENT = 0.10  # 10% от доступного баланса
TIMEFRAMES = {"1m": 1, "5m": 5, "15m": 15}  # 15м вместо 30м
MIN_TRADE_SECONDS = 120  
MIN_RANDOM_TRADE_SECONDS = 480  
MAX_RANDOM_TRADE_SECONDS = 780  
PAUSE_BETWEEN_TRADES = 0  
START_BANK = 100.0  
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
                "options": {"defaultType": "swap"}
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
            
            if not ohlcv: return None
                
            df = pd.DataFrame(ohlcv)
            df.columns = ["timestamp", "open", "high", "low", "close", "volume"]
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
        logging.info(f"[{self.now()}] PLACE MARKET ORDER -> side={side}, amount={amount_base:.6f}")
        
        if RUN_IN_PAPER or API_KEY == "" or API_SECRET == "":
            price = self.get_current_price()
            entry_time = datetime.utcnow()
            notional = amount_base * price
            margin = notional / LEVERAGE
            
            state["available"] -= margin
            close_time_seconds = random.randint(MIN_RANDOM_TRADE_SECONDS, MAX_RANDOM_TRADE_SECONDS)
            
            if "telegram_trade_counter" not in state: state["telegram_trade_counter"] = 1
            else: state["telegram_trade_counter"] += 1
            trade_number = state["telegram_trade_counter"]
            
            state["in_position"] = True
            state["position"] = {
                "side": "long" if side == "buy" else "short",
                "entry_price": price,
                "size_base": amount_base,
                "notional": notional,
                "margin": margin,
                "entry_time": entry_time.isoformat(),
                "close_time_seconds": close_time_seconds,
                "trade_number": trade_number
            }
            state["last_trade_time"] = entry_time.isoformat()
            
            if self.notifier:
                self.notifier.send_position_opened(state["position"], price, trade_number, state["balance"])
            
            if state["position"]["side"] == "long": self.signal_sender.send_open_long()
            else: self.signal_sender.send_open_short()
            
            return state["position"]

    def close_position(self, close_reason="unknown"):
        if not state["in_position"] or not state["position"]: return None
            
        side = state["position"]["side"]
        size = state["position"]["size_base"]
        logging.info(f"[{self.now()}] CLOSE POSITION -> {side} {size:.6f} Reason: {close_reason}")
        
        if RUN_IN_PAPER:
            price = self.get_current_price()
            entry_price = state["position"]["entry_price"]
            notional = state["position"]["notional"]
            
            pnl = (price - entry_price) * size if side == "long" else (entry_price - price) * size
            pnl_after_fee = pnl - (abs(notional) * 0.0003)
            
            state["available"] += state["position"]["margin"] + pnl_after_fee
            state["balance"] = state["available"]
            
            trade = {
                "time": datetime.utcnow().isoformat(),
                "side": side,
                "entry_price": entry_price,
                "exit_price": price,
                "size_base": size,
                "pnl": pnl_after_fee,
                "duration": self.calculate_duration(state["position"]["entry_time"]),
                "close_reason": close_reason
            }
            
            if self.notifier:
                self.notifier.send_position_closed(trade, state["position"].get("trade_number", 1), state["balance"])
            
            if side == "long": self.signal_sender.send_close_long()
            else: self.signal_sender.send_close_short()
            
            self.append_trade(trade)
            state["in_position"] = False
            state["position"] = None
            self.save_state_to_file()
            return trade

    def calculate_duration(self, entry_time_str):
        try:
            entry_time = datetime.fromisoformat(entry_time_str.replace('Z', '+00:00'))
            duration = datetime.utcnow() - entry_time
            return f"{int(duration.total_seconds() // 60)}м {int(duration.total_seconds() % 60)}с"
        except: return "N/A"

    def append_trade(self, trade):
        state["trades"].insert(0, trade)
        state["trades"] = state["trades"][:DASHBOARD_MAX]

    def get_current_price(self):
        try:
            if USE_SIMULATOR: return self.simulator.get_current_price()
            ticker = self.exchange.fetch_ticker(SYMBOL)
            return float(ticker["last"])
        except: return 3000.0

    def strategy_loop(self, should_continue=lambda: True):
        logging.info(f"Starting strategy loop with SAR 1m & 15m. RUN_IN_PAPER={RUN_IN_PAPER}")
        
        while should_continue():
            try:
                dirs = {}
                for tf in TIMEFRAMES.keys():
                    df = self.fetch_ohlcv_tf(tf)
                    dirs[tf] = self.get_direction_from_psar(df) if df is not None else None

                if any(d is None for d in dirs.values()):
                    time.sleep(5); continue

                dir_1m, dir_5m, dir_15m = dirs["1m"], dirs["5m"], dirs["15m"]
                
                # ИСПРАВЛЕННАЯ СТРОКА 172:
                logging.info(f"[{self.now()}] SAR: 1m:{dir_1m} 5m:{dir_5m} 15m:{dir_15m}")

                if state["in_position"]:
                    # Закрытие при смене минутного SAR
                    if dir_1m != state["position"]["side"]:
                        self.close_position(close_reason="sar_reversal")
                        state["skip_next_signal"] = True
                        self.save_state_to_file()
                else:
                    # Сброс флага пропуска при смене минутного тренда
                    if state["last_1m_dir"] and state["last_1m_dir"] != dir_1m:
                        if state["skip_next_signal"]:
                            logging.info(f"✅ Resetting skip flag: {state['last_1m_dir']} -> {dir_1m}")
                            state["skip_next_signal"] = False
                    
                    state["last_1m_dir"] = dir_1m
                    
                    # Вход: 1m совпадает с 15m
                    if dir_1m and dir_1m == dir_15m and not state["skip_next_signal"]:
                        logging.info(f"✅ Entry signal: 1m = 15m SAR = {dir_1m.upper()}")
                        price = self.get_current_price()
                        size, _ = self.compute_order_size_usdt(state["balance"], price)
                        self.place_market_order("buy" if dir_1m == "long" else "sell", size)
                        self.save_state_to_file()

                time.sleep(5)
            except Exception as e:
                logging.error(f"Loop error: {e}"); time.sleep(5)
