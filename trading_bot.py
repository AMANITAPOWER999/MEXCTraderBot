import os
import json
import time
import random
import ccxt
import logging
import pandas as pd
import pandas_ta as ta
from datetime import datetime, timedelta

# --- Конфигурация ---
SYMBOL = 'ETH/USDT'
TIMEFRAME_15M = '15m'
TIMEFRAME_5M = '5m'
TIMEFRAME_1M = '1m'
START_BANK = 100.0 # Начальный баланс для Paper Trading
STATE_FILE = 'bot_state.json'
RUN_IN_PAPER = os.getenv('RUN_IN_PAPER', '1') == '1' # '1' for Paper, '0' for Live

# SAR Parameters
SAR_ACCELERATION_START = 0.02
SAR_ACCELERATION_STEP = 0.02
SAR_ACCELERATION_MAX = 0.2

# Инициализация глобального состояния
state = {
    'balance': START_BANK,
    'available': START_BANK,
    'in_position': False,
    'position': None,
    'trades': [],
    'telegram_trade_counter': 0, # Счетчик закрытых/завершенных сделок для Telegram
    'skip_next_signal': False # Флаг для пропуска входа сразу после выхода
}

# --- Вспомогательные функции ---

def load_state():
    """Загрузка состояния бота из файла."""
    global state
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                loaded_state = json.load(f)
                # Обновление состояния, сохраняя дефолты если ключа нет
                for key, default_value in state.items():
                    # Специальная обработка для trades
                    if key == 'trades' and key in loaded_state:
                         state[key] = loaded_state[key]
                    else:
                        state[key] = loaded_state.get(key, default_value)
                logging.info(f"State loaded from {STATE_FILE}. Current balance: ${state['balance']:.2f}")
                
                # Дополнительная проверка: убедимся, что counter существует
                if 'telegram_trade_counter' not in state:
                    state['telegram_trade_counter'] = len(state['trades'])
                    logging.warning(f"telegram_trade_counter missing, initializing to {state['telegram_trade_counter']}")

        except Exception as e:
            logging.error(f"Error loading state: {e}")
            pass
    else:
        logging.info("State file not found. Starting with default state.")

load_state()

# --- Класс TradingBot ---

class TradingBot:
    def __init__(self, telegram_notifier=None):
        self.exchange = self._initialize_exchange()
        self.telegram_notifier = telegram_notifier
        # Максимальный риск на сделку 20% от стартового банка (для Paper Trading)
        self.max_trade_size = START_BANK * 0.2 
        self.max_leverage = 5 
        logging.info(f"Initialized bot. Paper Mode: {RUN_IN_PAPER}")
        
    def _initialize_exchange(self):
        """Инициализация биржи (Binance)"""
        api_key = os.getenv('BINANCE_API_KEY')
        secret = os.getenv('BINANCE_SECRET')

        if not api_key or not secret:
            logging.error("Binance API credentials not set.")
            return None

        exchange = ccxt.binance({
            'apiKey': api_key,
            'secret': secret,
            'enableRateLimit': True,
            'options': {
                'defaultType': 'future',
            }
        })
        return exchange

    def get_current_price(self):
        """Получение текущей цены."""
        try:
            ticker = self.exchange.fetch_ticker(SYMBOL)
            return ticker['last']
        except Exception as e:
            logging.error(f"Error fetching current price: {e}")
            return None

    def save_state_to_file(self):
        """Сохранение текущего состояния бота в файл."""
        try:
            with open(STATE_FILE, 'w') as f:
                json.dump(state, f, indent=4, default=str) 
        except Exception as e:
            logging.error(f"Error saving state: {e}")

    # --- OHLCV и Индикаторы ---

    def fetch_ohlcv_tf(self, timeframe, limit=100):
        """Получение исторических данных."""
        try:
            ohlcv = self.exchange.fetch_ohlcv(SYMBOL, timeframe, limit=limit)

            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('datetime', inplace=True)
            return df[['open', 'high', 'low', 'close', 'volume']]
        except Exception as e:
            logging.error(f"Error fetching OHLCV for {timeframe}: {e}")
            return None

    def compute_psar(self, df):
        """Расчет Parabolic SAR."""
        # pandas_ta (ta) SAR
        psar = ta.psar(df['high'], df['low'], df['close'],
                       af0=SAR_ACCELERATION_START,
                       step=SAR_ACCELERATION_STEP,
                       max=SAR_ACCELERATION_MAX)
        
        last_psar = psar['PSARl'].iloc[-1]
        if last_psar > 0 and psar['PSARs'].iloc[-1] == 0:
            return psar['PSARl']
        elif psar['PSARs'].iloc[-1] > 0 and last_psar == 0:
             return psar['PSARs']
        return psar['PSARl'].fillna(psar['PSARs'])


    def get_direction_from_psar(self, df):
        """Определение направления: 'long' или 'short'."""
        if df is None or len(df) < 3:
            return None

        # Расчет SAR для определения направления
        psar = self.compute_psar(df)
        
        last_close = df['close'].iloc[-1]
        last_psar = psar.iloc[-1]

        # Если SAR ниже цены -> Long (покупка)
        if last_close > last_psar:
            return 'long'
        # Если SAR выше цены -> Short (продажа)
        elif last_close < last_psar:
            return 'short'
        else:
            return None

    def get_current_directions(self):
        """Получение текущих направлений SAR для всех ТФ."""
        directions = {}
        for tf in [TIMEFRAME_15M, TIMEFRAME_5M, TIMEFRAME_1M]:
            df = self.fetch_ohlcv_tf(tf, limit=50)
            directions[tf] = self.get_direction_from_psar(df)
        return directions

    # --- Управление позицией (Paper Trading Logic) ---

    def get_trade_size(self, current_price, side):
        """Расчет размера сделки в USDT и в монетах."""
        # Риск 1% от баланса, затем умножаем на плечо (5x)
        risk_percent = 0.01 
        
        # Определяем сумму залога (Margin)
        usdt_amount = state['available'] * risk_percent * self.max_leverage 
        
        # Ограничиваем максимальный размер
        if usdt_amount > self.max_trade_size:
            usdt_amount = self.max_trade_size

        if usdt_amount > state['available']:
            usdt_amount = state['available']

        if usdt_amount <= 0:
            return 0, 0
        
        # Размер в монетах 
        coin_amount = usdt_amount / current_price
        
        # Эмуляция комиссии (0.04% за вход)
        fee = usdt_amount * 0.0004
        
        return usdt_amount - fee, coin_amount 

    def open_position(self, side, usdt_amount, coin_amount, price):
        """Открытие позиции (симуляция)."""
        global state
        
        if state['in_position']:
            logging.warning("Attempted to open position but one is already open.")
            return False

        # Обновление счетчика сделок для Telegram
        state['telegram_trade_counter'] += 1
        trade_number = state['telegram_trade_counter']

        new_position = {
            'entry_time': datetime.utcnow().isoformat(),
            'side': side,
            'entry_price': price,
            'usdt_amount': usdt_amount,
            'coin_amount': coin_amount,
            'leverage': self.max_leverage,
            'trade_number': trade_number, 
        }

        # Обновление состояния
        state['in_position'] = True
        state['position'] = new_position
        state['available'] -= usdt_amount 
        
        logging.info(f"🚀 Opened {side.upper()} position #{trade_number}: {coin_amount:.4f} {SYMBOL}. Price: ${price:.2f}. Margin: ${usdt_amount:.2f}")

        if self.telegram_notifier:
            self.telegram_notifier.send_entry_notification(new_position, state['balance'])

        self.save_state_to_file()
        return True

    def close_position(self, close_reason):
        """Закрытие позиции (симуляция)."""
        global state
        if not state['in_position']:
            return None

        pos = state['position']
        entry_price = pos['entry_price']
        coin_amount = pos['coin_amount']
        usdt_amount = pos['usdt_amount']
        side = pos['side']
        trade_number = pos['trade_number']
        
        current_price = self.get_current_price()
        
        # PnL Calculation (Leveraged)
        if side == 'long':
            pnl_usdt = coin_amount * (current_price - entry_price) * pos['leverage']
        else: # short
            pnl_usdt = coin_amount * (entry_price - current_price) * pos['leverage']
            
        # Эмуляция комиссии при закрытии 
        fee = (coin_amount * current_price) * 0.0004 
        
        final_pnl = pnl_usdt - fee
        new_balance = state['balance'] + final_pnl
        
        # Сохранение сделки в историю
        trade_record = {
            'trade_number': trade_number,
            'time': datetime.utcnow().isoformat(),
            'side': side,
            'entry_price': entry_price,
            'entry_time': pos['entry_time'],
            'exit_price': current_price,
            'pnl_usdt': final_pnl,
            'pnl_percent': (final_pnl / usdt_amount) * 100 if usdt_amount > 0 else 0,
            'reason': close_reason,
            'balance_after': new_balance
        }
        
        state['trades'].append(trade_record)
        
        # Обновление состояния
        state['balance'] = new_balance
        state['available'] = new_balance 
        state['in_position'] = False
        state['position'] = None
        
        logging.info(f"🛑 Closed {side.upper()} position #{trade_number}. PnL: ${final_pnl:.2f}. New Balance: ${new_balance:.2f}. Reason: {close_reason}")

        if self.telegram_notifier:
            self.telegram_notifier.send_exit_notification(trade_record, current_price, new_balance)

        self.save_state_to_file()
        return trade_record

    # --- Основной цикл стратегии ---

    def strategy_loop(self, should_continue):
        """Основной цикл для выполнения стратегии."""
        while should_continue():
            try:
                # 1. Получаем текущие направления SAR
                directions = self.get_current_directions()
                dir_15m = directions.get(TIMEFRAME_15M)
                dir_5m = directions.get(TIMEFRAME_5M)
                dir_1m = directions.get(TIMEFRAME_1M)
                current_price = self.get_current_price()
                
                if not current_price:
                    logging.warning("Could not fetch current price. Skipping cycle.")
                    time.sleep(10)
                    continue

                # Вывод отладочной информации 
                if not state["in_position"]:
                    logging.info(f"Price: ${current_price:.2f} | 15m: {dir_15m} | 5m: {dir_5m} | 1m: {dir_1m} | Balance: ${state['balance']:.2f}")


                # 2. Логика закрытия позиции
                if state["in_position"]:
                    
                    pos = state['position']
                    side = pos['side']

                    # УСЛОВИЕ ВЫХОДА: ТОЛЬКО СМЕНА 5m SAR
                    if dir_5m and dir_5m != side:
                        logging.info(f"Closing because 5m SAR changed from {side} to {dir_5m}")
                        self.close_position(close_reason="sar_reversal_5m") 
                        state["skip_next_signal"] = True  
                        self.save_state_to_file()
                        time.sleep(1) 
                        continue

                    # TAKE PROFIT УСЛОВИЕ УДАЛЕНО

                # 3. Логика открытия позиции
                elif not state["in_position"]:
                    
                    if state["skip_next_signal"]:
                        logging.info("Skipping signal due to recent exit.")
                        state["skip_next_signal"] = False
                        self.save_state_to_file()
                        time.sleep(5)
                        continue

                    side_to_enter = None
                    
                    # Условие входа: SAR на 5m и 1m должны быть согласованы
                    if dir_1m == 'long' and dir_5m == 'long':
                        side_to_enter = 'long'
                    elif dir_1m == 'short' and dir_5m == 'short':
                        side_to_enter = 'short'
                    
                    # 15m игнорируется

                    if side_to_enter:
                        
                        # Расчет размера сделки
                        usdt_amount, coin_amount = self.get_trade_size(current_price, side_to_enter)
                        
                        if usdt_amount > 0 and coin_amount > 0:
                            self.open_position(side_to_enter, usdt_amount, coin_amount, current_price)
                        else:
                            logging.warning(f"Calculated trade size is zero or invalid. Balance: ${state['available']:.2f}")

                # 4. Пауза и сохранение
                self.save_state_to_file()
                
                # Основной цикл проверяется каждые 15 секунд
                time.sleep(15) 

            except Exception as e:
                logging.error(f"Strategy loop error: {e}")
                time.sleep(30) # Более длительная пауза при ошибке
