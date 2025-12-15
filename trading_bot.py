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
# Google Sheets integration removed

# ========== Конфигурация ==========
API_KEY = os.getenv("ASCENDEX_API_KEY", "")
API_SECRET = os.getenv("ASCENDEX_SECRET", "")
RUN_IN_PAPER = os.getenv("RUN_IN_PAPER", "1") == "1"
USE_SIMULATOR = os.getenv("USE_SIMULATOR", "0") == "1"  # Переключаемся на реальные данные с новыми API ключами

SYMBOL = "ETH/USDT:USDT"  # ASCENDEX futures symbol format  # инструмент
LEVERAGE = 500  # плечо x500
ISOLATED = True  # изолированная маржа
POSITION_PERCENT = 0.10  # 10% от доступного баланса
TIMEFRAMES = {"1m": 1, "5m": 5, "15m": 15}  # Меняем 3m на 5m (MEXC не поддерживает 3m)
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
        # Google Sheets integration removed
        
        # Выбираем режим работы: симулятор или реальная биржа
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
                    "defaultType": "swap",  # Enable futures/swap trading for leverage
                }
            })
            logging.info("ASCENDEX configured for swap/futures trading with leverage support")
            
            # Configure leverage and margin mode during initialization
            if API_KEY and API_SECRET:
                try:
                    # Set margin mode to isolated
                    if ISOLATED:
                        self.exchange.set_margin_mode('isolated', SYMBOL)
                        logging.info(f"Margin mode set to ISOLATED for {SYMBOL}")
                    
                    # Set leverage
                    self.exchange.set_leverage(LEVERAGE, SYMBOL)
                    logging.info(f"Leverage set to {LEVERAGE}x for {SYMBOL}")
                except Exception as e:
                    logging.error(f"Failed to configure leverage/margin mode: {e}")
                    logging.error("Trading will continue in paper mode to avoid order rejections")
        
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
        """
        Возвращает pd.DataFrame с колонками: timestamp, open, high, low, close, volume
        """
        try:
            if USE_SIMULATOR and self.simulator:
                # Используем симулятор
                ohlcv = self.simulator.fetch_ohlcv(tf, limit=limit)
            else:
                # Используем реальную биржу
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
        """
        Возвращает Series с PSAR (последняя точка).
        Используем ta.trend.PSARIndicator
        """
        if df is None or len(df) < 5:
            return None
        try:
            high_series = pd.Series(df["high"].values)
            low_series = pd.Series(df["low"].values)
            close_series = pd.Series(df["close"].values)
            # Повышенная чувствительность SAR (увеличены step и max_step умеренно)
            psar_ind = PSARIndicator(high=high_series, low=low_series, close=close_series, step=0.05, max_step=0.5)
            psar = psar_ind.psar()
            return psar
        except Exception as e:
            logging.error(f"PSAR compute error: {e}")
            return None

    def get_direction_from_psar(self, df: pd.DataFrame):
        """
        Возвращает направление 'long' или 'short' на основе сравнения последней close и psar
        """
        psar = self.compute_psar(df)
        if psar is None:
            return None
        last_psar = psar.iloc[-1]
        last_close = df["close"].iloc[-1]
        return "long" if last_close > last_psar else "short"


    def get_current_directions(self):
        """Get current PSAR directions for all timeframes"""
        directions = {}
        for tf in TIMEFRAMES.keys():
            df = self.fetch_ohlcv_tf(tf)
            if df is not None:
                directions[tf] = self.get_direction_from_psar(df)
            else:
                directions[tf] = None
        return directions

    def compute_order_size_usdt(self, balance, price):
        # позиция (ноционал) = balance * POSITION_PERCENT * LEVERAGE
        notional = balance * POSITION_PERCENT * LEVERAGE
        base_amount = notional / price  # количество базового актива (ETH)
        return base_amount, notional

    def place_market_order(self, side: str, amount_base: float):
        """
        side: 'buy' или 'sell' (для открытия позиции)
        amount_base: количество в базовой валюте (ETH)
        """
        logging.info(f"[{self.now()}] PLACE MARKET ORDER -> side={side}, amount={amount_base:.6f}")
        
        if RUN_IN_PAPER or API_KEY == "" or API_SECRET == "":
            # Бумажная торговля — симулируем ордер
            price = self.get_current_price()
            entry_price = price
            entry_time = datetime.utcnow()
            notional = amount_base * entry_price
            margin = notional / LEVERAGE  # Маржа, которую нужно зарезервировать
            
            # Вычитаем маржу из доступного баланса
            state["available"] -= margin
            
            # Генерируем случайное время закрытия от 8 до 13 минут
            close_time_seconds = random.randint(MIN_RANDOM_TRADE_SECONDS, MAX_RANDOM_TRADE_SECONDS)
            
            # Генерируем номер сделки для Telegram (отдельный счетчик)
            if "telegram_trade_counter" not in state:
                state["telegram_trade_counter"] = 1
            else:
                state["telegram_trade_counter"] += 1
            trade_number = state["telegram_trade_counter"]
            
            state["in_position"] = True
            state["position"] = {
                "side": "long" if side == "buy" else "short",
                "entry_price": entry_price,
                "size_base": amount_base,
                "notional": notional,
                "margin": margin,  # Сохраняем маржу для возврата при закрытии
                "entry_time": entry_time.isoformat(),
                "close_time_seconds": close_time_seconds,  # Случайное время закрытия для этой позиции
                "trade_number": trade_number  # Сохраняем номер сделки
            }
            state["last_trade_time"] = entry_time.isoformat()
            
            # Логируем информацию об открытой позиции с случайным временем закрытия
            logging.info(f"Position opened with random close time: {close_time_seconds}s ({close_time_seconds/60:.1f} minutes)")
            
            # Send Telegram notification for position opening
            if self.notifier:
                self.notifier.send_position_opened(state["position"], price, trade_number, state["balance"])
            
            # Send signal to external service
            if state["position"]["side"] == "long":
                self.signal_sender.send_open_long()
            else:
                self.signal_sender.send_open_short()
            
            # Google Sheets reporting removed
            
            return state["position"]
        else:
            # Реальная торговля
            try:
                # Установка плеча
                try:
                    self.exchange.set_leverage(LEVERAGE, SYMBOL)
                except Exception as e:
                    logging.error(f"set_leverage failed: {e}")

                # Создание рыночного ордера
                order = self.exchange.create_market_buy_order(SYMBOL, amount_base) if side == "buy" else self.exchange.create_market_sell_order(SYMBOL, amount_base)
                logging.info(f"Order response: {order}")
                
                # После успешного создания заполняем state
                entry_price = float(order.get("average", order.get("price", self.get_current_price())))
                entry_time = datetime.utcnow()
                notional = amount_base * entry_price
                margin = notional / LEVERAGE  # Маржа, которую нужно зарезервировать
                
                # Вычитаем маржу из доступного баланса
                state["available"] -= margin
                
                # Генерируем случайное время закрытия от 8 до 13 минут
                close_time_seconds = random.randint(MIN_RANDOM_TRADE_SECONDS, MAX_RANDOM_TRADE_SECONDS)
                
                state["in_position"] = True
                state["position"] = {
                    "side": "long" if side == "buy" else "short",
                    "entry_price": entry_price,
                    "size_base": amount_base,
                    "notional": notional,
                    "margin": margin,  # Сохраняем маржу для возврата при закрытии
                    "entry_time": entry_time.isoformat(),
                    "close_time_seconds": close_time_seconds  # Случайное время закрытия для этой позиции
                }
                state["last_trade_time"] = entry_time.isoformat()
                
                # Логируем информацию об открытой позиции с случайным временем закрытия
                logging.info(f"Position opened with random close time: {close_time_seconds}s ({close_time_seconds/60:.1f} minutes)")
                
                # Send signal to external service
                if state["position"]["side"] == "long":
                    self.signal_sender.send_open_long()
                else:
                    self.signal_sender.send_open_short()
                
                # Telegram notification removed (already sent in paper trading branch)
                
                return state["position"]
            except Exception as e:
                logging.error(f"place_market_order error: {e}")
                return None

    def close_position(self, close_reason="unknown"):
        if not state["in_position"] or not state["position"]:
            return None
            
        side = state["position"]["side"]
        size = state["position"]["size_base"]
        # Для закрытия: делаем ордер в противоположную сторону
        close_side = "sell" if side == "long" else "buy"
        logging.info(f"[{self.now()}] CLOSE POSITION -> {close_side} {size:.6f}")
        
        if RUN_IN_PAPER or API_KEY == "" or API_SECRET == "":
            # симуляция: считаем результат PnL по цене закрытия
            price = self.get_current_price()
            entry_price = state["position"]["entry_price"]
            notional = state["position"]["notional"]
            
            if state["position"]["side"] == "long":
                pnl = (price - entry_price) * size
            else:
                pnl = (entry_price - price) * size
                
            # Учитываем комиссии упрощённо (0.03% на сделку)
            fee = abs(notional) * 0.0003
            pnl_after_fee = pnl - fee
            
            # Возвращаем маржу + PnL
            margin = state["position"].get("margin", notional / LEVERAGE)
            previous_balance = state["balance"]
            state["available"] += margin + pnl_after_fee  # Возвращаем маржу + PnL
            state["balance"] = state["available"]
            
            trade = {
                "time": datetime.utcnow().isoformat(),
                "side": state["position"]["side"],
                "entry_price": entry_price,
                "exit_price": price,
                "size_base": size,
                "pnl": pnl_after_fee,
                "notional": notional,
                "duration": self.calculate_duration(state["position"]["entry_time"]),
                "close_reason": close_reason
            }
            
            # Send Telegram notification for position closing
            if self.notifier:
                trade_number = state["position"].get("trade_number", 1)
                self.notifier.send_position_closed(trade, trade_number, state["balance"])
                # Balance update notification removed by user request
            
            # Send signal to external service
            if state["position"]["side"] == "long":
                self.signal_sender.send_close_long()
            else:
                self.signal_sender.send_close_short()
            
            # Google Sheets reporting removed
            
            self.append_trade(trade)
            
            # сброс позиции
            state["in_position"] = False
            state["position"] = None
            state["last_trade_time"] = datetime.utcnow().isoformat()
            self.save_state_to_file()
            return trade
        else:
            try:
                # реальный ордер закрытия
                if side == "long":
                    order = self.exchange.create_market_sell_order(SYMBOL, size)
                else:
                    order = self.exchange.create_market_buy_order(SYMBOL, size)
                    
                logging.info(f"Close order response: {order}")
                
                # Получаем цену закрытия
                exit_price = float(order.get("average", order.get("price", self.get_current_price())))
                entry_price = state["position"]["entry_price"]
                
                if state["position"]["side"] == "long":
                    pnl = (exit_price - entry_price) * size
                else:
                    pnl = (entry_price - exit_price) * size
                    
                fee = abs(state["position"]["notional"]) * 0.0003
                pnl_after_fee = pnl - fee
                
                # Возвращаем маржу + PnL
                margin = state["position"].get("margin", abs(state["position"]["notional"]) / LEVERAGE)
                previous_balance = state["balance"]
                state["available"] += margin + pnl_after_fee  # Возвращаем маржу + PnL
                state["balance"] = state["available"]
                
                trade = {
                    "time": datetime.utcnow().isoformat(),
                    "side": state["position"]["side"],
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "size_base": size,
                    "pnl": pnl_after_fee,
                    "notional": state["position"]["notional"],
                    "duration": self.calculate_duration(state["position"]["entry_time"]),
                    "close_reason": close_reason
                }
                
                self.append_trade(trade)
                
                # Send signal to external service
                if trade["side"] == "long":
                    self.signal_sender.send_close_long()
                else:
                    self.signal_sender.send_close_short()
                
                # Telegram notification removed (already sent in paper trading branch)
                
                state["in_position"] = False
                state["position"] = None
                self.save_state_to_file()
                return trade
            except Exception as e:
                logging.error(f"close_position error: {e}")
                return None

    def calculate_duration(self, entry_time_str):
        """Calculate trade duration in human readable format"""
        try:
            entry_time = datetime.fromisoformat(entry_time_str.replace('Z', '+00:00'))
            duration = datetime.utcnow() - entry_time
            
            minutes = int(duration.total_seconds() // 60)
            seconds = int(duration.total_seconds() % 60)
            
            if minutes > 0:
                return f"{minutes}м {seconds}с"
            else:
                return f"{seconds}с"
        except:
            return "N/A"

    def append_trade(self, trade):
        state["trades"].insert(0, trade)
        # keep only last DASHBOARD_MAX
        state["trades"] = state["trades"][:DASHBOARD_MAX]

    def get_current_price(self):
        try:
            if USE_SIMULATOR and self.simulator:
                # Используем симулятор
                return self.simulator.get_current_price()
            else:
                # Используем реальную биржу
                ticker = self.exchange.fetch_ticker(SYMBOL)
                return float(ticker["last"])
        except Exception as e:
            logging.error(f"fetch ticker error: {e}")
            # fallback
            if RUN_IN_PAPER and state["position"] is None:
                return 3000.0  # Default ETH price for paper trading
            else:
                return float(state["position"]["entry_price"]) if state["position"] else 3000.0

    def strategy_loop(self, should_continue=lambda: True):
        logging.info(f"Starting strategy loop. RUN_IN_PAPER={RUN_IN_PAPER}")
        
        while should_continue():
            try:
                # 1) Получаем свечи и направления
                dfs = {}
                dirs = {}
                for tf in TIMEFRAMES.keys():
                    df = self.fetch_ohlcv_tf(tf)
                    dfs[tf] = df
                    if df is not None:
                        dirs[tf] = self.get_direction_from_psar(df)
                    else:
                        dirs[tf] = None

                # пропускаем итерацию, если нет данных
                if any(d is None for d in dirs.values()):
                    time.sleep(5)
                    continue

                dir_1m = dirs["1m"]
                dir_5m = dirs["5m"]
                dir_15m = dirs["15m"]
                
                logging.info(f"[{self.now()}] SAR directions => 1m:{dir_1m} 5m:{dir_5m} 15m:{dir_15m}")
                
                # Store current SAR directions for sheets reporting
                self._current_sar_directions = dirs

                # Проверка на закрытие (если в позиции)
                if state["in_position"]:
                    entry_t = datetime.fromisoformat(state["position"]["entry_time"])
                    trade_duration = (datetime.utcnow() - entry_t).total_seconds()
                    
                    # Принудительное закрытие по случайному времени (8-13 минут)
                    position_close_time = state["position"].get("close_time_seconds", MAX_RANDOM_TRADE_SECONDS)
                    if trade_duration >= position_close_time:
                        minutes = position_close_time / 60
                        logging.info(f"Closing position due to random time limit ({position_close_time}s = {minutes:.1f}min)")
                        self.close_position(close_reason="random_time")
                        state["skip_next_signal"] = True  # устанавливаем флаг пропуска
                        self.save_state_to_file()
                        time.sleep(1)
                        continue
                    
                    # Закрытие по смене 1m SAR (мгновенно)
                    if dir_1m != state["position"]["side"]:
                        logging.info("Closing because 1m SAR changed")
                        self.close_position(close_reason="sar_reversal")
                        state["skip_next_signal"] = True  # устанавливаем флаг пропуска
                        self.save_state_to_file()
                        time.sleep(1)
                        continue

                # Если не в позиции — проверяем условие входа: SAR 15m и 1m совпадают
                else:
                    # Отслеживание смены 1m SAR для сброса флага пропуска
                    if state["last_1m_dir"] and state["last_1m_dir"] != dir_1m:
                        if state["skip_next_signal"]:
                            logging.info(f"✅ Resetting skip flag after 1m SAR change: {state['last_1m_dir']} -> {dir_1m}")
                            state["skip_next_signal"] = False  # сбрасываем флаг и РАЗРЕШАЕМ торговлю
                            self.save_state_to_file()
                    
                    # Сохраняем текущее направление для отслеживания смен
                    state["last_1m_dir"] = dir_1m
                    
                    # Вход когда 15m и 1m SAR совпадают (только если не нужно пропускать)
                    # SAR-ONLY стратегия: вход при совпадении 15m и 1m SAR
                    if dir_1m in ["long", "short"] and dir_1m == dir_15m and not state["skip_next_signal"]:
                        logging.info(f"✅ Entry signal: 15m SAR = 1m SAR = {dir_1m.upper()}")
                        
                        # вход в позицию
                        side = "buy" if dir_1m == "long" else "sell"
                        price = self.get_current_price()
                        # compute order size
                        size_base, notional = self.compute_order_size_usdt(state["balance"], price if price > 0 else 1.0)
                        logging.info(f"Signal to OPEN {side} — size_base={size_base:.6f} notional=${notional:.2f} price={price}")
                        
                        # Place order (маржа уже вычитается в place_market_order)
                        pos = self.place_market_order(side, amount_base=size_base)
                        
                        self.save_state_to_file()
                        time.sleep(1)
                    elif state["skip_next_signal"] and dir_1m in ["long", "short"] and dir_1m == dir_15m:
                        logging.info(f"🔄 Skip flag active: 15m:{dir_15m} = 1m:{dir_1m} (will trade after next 1m change)")
                    else:
                        # нет общего сигнала
                        pass

                time.sleep(5)  # маленькая пауза в основном цикле
            except Exception as e:
                logging.error(f"Main loop error: {e}")
                time.sleep(5)
