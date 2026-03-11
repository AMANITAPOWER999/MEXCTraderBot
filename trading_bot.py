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

SYMBOL = "ETH/USDT"  # ASCENDEX/MEXC futures symbol format
LEVERAGE = 500  # плечо x500
ISOLATED = True  # изолированная маржа
POSITION_PERCENT = 0.10  # 10% от доступного баланса
TIMEFRAMES = {"1m": 1, "5m": 5, "30m": 30}  # Установлены 3 таймфрейма: 1м, 5м, 30м
MIN_TRADE_SECONDS = 120  # минимальная длительность сделки 2 минуты
MIN_RANDOM_TRADE_SECONDS = 480  # минимальная случайная длительность сделки 8 минут
MAX_RANDOM_TRADE_SECONDS = 780  # максимальная случайная длительность сделки 13 минут
PAUSE_BETWEEN_TRADES = 0  # пауза между сделками убрана
START_BANK = 100.0  # стартовый банк (для бумажной торговли / учета)
DASHBOARD_MAX = 20

# ========== Глобальные переменные состояния ==========
state = {
    "balance": START_BANK,
    "available": START_BANK,
    "in_position": False,
    "position": None,  # dict: {side, entry_price, size_base, entry_time}
    "last_trade_time": None,
    "last_1m_dir": None,
    "one_min_flip_count": 0,
    "skip_next_signal": False,  # пропускать следующий сигнал входа
    "trades": []  # список последних сделок
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
                    logging.error(f"Failed to configure exchange: {e}")
        
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
                try:
                    ohlcv = self.exchange.fetch_ohlcv("ETH/USDT", timeframe=tf, limit=limit)
                except:
                    ohlcv = self.exchange.fetch_ohlcv(SYMBOL, timeframe=tf, limit=limit)
            
            if not ohlcv or len(ohlcv) < 5:
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
            psar_ind = PSARIndicator(high=df["high"].astype(float), low=df["low"].astype(float), close=df["close"].astype(float), step=0.05, max_step=0.5)
            return psar_ind.psar()
        except Exception as e:
            logging.error(f"PSAR compute error: {e}")
            return None

    def get_direction_from_psar(self, df: pd.DataFrame):
        psar = self.compute_psar(df)
        if psar is None or len(psar) == 0:
            return None
        last_psar = psar.iloc[-1]
        last_close = float(df["close"].iloc[-1])
        if pd.isna(last_psar):
            return None
        return "long" if last_close > last_psar else "short"

    def get_current_directions(self):
        directions = {}
        for tf in TIMEFRAMES.keys():
            df = self.fetch_ohlcv_tf(tf)
            directions[tf] = self.get_direction_from_psar(df) if df is not None else None
        return directions

    def compute_order_size_usdt(self, balance, price):
        notional = balance * POSITION_PERCENT * LEVERAGE
        base_amount = notional / price
        return base_amount, notional

    def place_market_order(self, side: str, amount_base: float):
        if RUN_IN_PAPER or not API_KEY:
            price = self.get_current_price()
            entry_time = self.now()
            notional = amount_base * price
            margin = notional / LEVERAGE
            state["available"] -= margin
            
            if "telegram_trade_counter" not in state:
                state["telegram_trade_counter"] = 1
            else:
                state["telegram_trade_counter"] += 1
            
            state["in_position"] = True
            state["position"] = {
                "side": "long" if side == "buy" else "short",
                "entry_price": price,
                "size_base": amount_base,
                "notional": notional,
                "margin": margin,
                "entry_time": entry_time.isoformat(),
                "trade_number": state["telegram_trade_counter"]
            }
            
            if self.notifier:
                self.notifier.send_position_opened(state["position"], price, state["position"]["trade_number"], state["balance"])
            
            if side == "buy": self.signal_sender.send_open_long()
            else: self.signal_sender.send_open_short()
            
            return state["position"]
        else:
            try:
                order = self.exchange.create_market_buy_order(SYMBOL, amount_base) if side == "buy" else self.exchange.create_market_sell_order(SYMBOL, amount_base)
                price = self.get_price_from_order(order)
                entry_time = self.now()
                notional = amount_base * price
                margin = notional / LEVERAGE
                state["available"] -= margin
                state["in_position"] = True
                state["position"] = {
                    "side": "long" if side == "buy" else "short",
                    "entry_price": price,
                    "size_base": amount_base,
                    "notional": notional,
                    "margin": margin,
                    "entry_time": entry_time.isoformat()
                }
                if side == "buy": self.signal_sender.send_open_long()
                else: self.signal_sender.send_open_short()
                return state["position"]
            except Exception as e:
                logging.error(f"Order error: {e}")
                return None

    def get_price_from_order(self, order):
        if not order: return self.get_current_price()
        for field in ['average', 'price']:
            if order.get(field): return float(order[field])
        info = order.get('info', {})
        for field in ['avgPrice', 'price']:
            if info.get(field): return float(info[field])
        return self.get_current_price()

    def close_position(self, close_reason="unknown"):
        if not state["in_position"]: return None
        side = state["position"]["side"]
        size = state["position"]["size_base"]
        
        if RUN_IN_PAPER or not API_KEY:
            price = self.get_current_price()
            entry_price = state["position"]["entry_price"]
            pnl = (price - entry_price) * size if side == "long" else (entry_price - price) * size
            pnl -= abs(state["position"]["notional"]) * 0.0003
            
            state["available"] += state["position"]["margin"] + pnl
            state["balance"] = state["available"]
            
            trade = {
                "time": self.now().isoformat(),
                "side": side,
                "entry_price": entry_price,
                "exit_price": price,
                "size_base": size,
                "pnl": pnl,
                "duration": self.calculate_duration(state["position"]["entry_time"]),
                "close_reason": close_reason
            }
            
            if self.notifier:
                self.notifier.send_position_closed(trade, state["position"].get("trade_number", 1), state["balance"])
            
            self.append_trade(trade)
            state["in_position"] = False
            state["position"] = None
            self.save_state_to_file()
            return trade
        else:
            try:
                order = self.exchange.create_market_sell_order(SYMBOL, size) if side == "long" else self.exchange.create_market_buy_order(SYMBOL, size)
                exit_price = self.get_price_from_order(order)
                entry_price = state["position"]["entry_price"]
                pnl = (exit_price - entry_price) * size if side == "long" else (entry_price - exit_price) * size
                pnl -= abs(state["position"]["notional"]) * 0.0003
                state["available"] += state["position"]["margin"] + pnl
                state["balance"] = state["available"]
                trade = {
                    "time": self.now().isoformat(),
                    "side": side,
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "pnl": pnl,
                    "duration": self.calculate_duration(state["position"]["entry_time"]),
                    "close_reason": close_reason
                }
                self.append_trade(trade)
                state["in_position"] = False
                state["position"] = None
                self.save_state_to_file()
                return trade
            except Exception as e:
                logging.error(f"Close error: {e}")
                return None

    def calculate_duration(self, entry_time_str):
        try:
            duration = self.now() - datetime.fromisoformat(entry_time_str.replace('Z', '+00:00'))
            m, s = divmod(int(duration.total_seconds()), 60)
            return f"{m}м {s}с" if m > 0 else f"{s}с"
        except: return "N/A"

    def append_trade(self, trade):
        state["trades"].insert(0, trade)
        state["trades"] = state["trades"][:DASHBOARD_MAX]

    def get_current_price(self):
        try:
            if USE_SIMULATOR: return self.simulator.get_current_price()
            try: ticker = self.exchange.fetch_ticker("ETH/USDT")
            except: ticker = self.exchange.fetch_ticker(SYMBOL)
            return float(ticker["last"])
        except: return 3000.0

    def strategy_loop(self, should_continue=lambda: True):
        while should_continue():
            try:
                dirs = self.get_current_directions()
                if any(d is None for d in dirs.values()):
                    time.sleep(5)
                    continue

                d1, d5, d30 = dirs["1m"], dirs["5m"], dirs["30m"]
                logging.info(f"[{self.now()}] SAR: 1m={d1}, 5m={d5}, 30m={d30}")

                if state["in_position"]:
                    if d1 != state["position"]["side"]:
                        self.close_position(close_reason="sar_reversal")
                        state["skip_next_signal"] = True
                        self.save_state_to_file()
                else:
                    if state["last_1m_dir"] and state["last_1m_dir"] != d1:
                        state["skip_next_signal"] = False
                    state["last_1m_dir"] = d1
                    
                    if d1 and d1 == d5 == d30 and not state["skip_next_signal"]:
                        price = self.get_current_price()
                        size, _ = self.compute_order_size_usdt(state["balance"], price)
                        self.place_market_order("buy" if d1 == "long" else "sell", size)
                        self.save_state_to_file()
                
                time.sleep(5)
