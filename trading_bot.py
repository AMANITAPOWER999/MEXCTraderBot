import os
import time
import json
import logging
from datetime import datetime

import ccxt
import pandas as pd
from ta.trend import PSARIndicator
from market_simulator import MarketSimulator
from signal_sender import SignalSender

# ========== Конфигурация ==========
SYMBOL = "BTC/USDT:USDT"      # Смена на BTC
LEVERAGE = 500
POSITION_PERCENT = 0.10
TIMEFRAMES = {"1m": 1, "5m": 5, "30m": 30} # Набор таймфреймов для анализа
STATE_FILE = "goldantilopa_btc_state.json"

class TradingBot:
    def __init__(self):
        self.signal_sender = SignalSender()
        self.exchange = ccxt.ascendex({
            "apiKey": os.getenv("ASCENDEX_API_KEY", ""),
            "secret": os.getenv("ASCENDEX_SECRET", ""),
            "enableRateLimit": True,
            "options": {"defaultType": "swap"}
        })
        self.load_state()

    # ... (методы load_state / save_state / fetch_ohlcv_tf остаются прежними)

    def strategy_loop(self):
        logging.info("🚀 Бот запущен: BTC | Вход 1-5-30 | Выход 1м")
        
        while True:
            try:
                dirs = self.get_current_directions()
                d1, d5, d30 = dirs.get("1m"), dirs.get("5m"), dirs.get("30m")

                if not all([d1, d5, d30]):
                    time.sleep(10); continue

                # --- ЛОГИКА ВЫХОДА (Смена тренда на 1м) ---
                if state["in_position"]:
                    current_side = state["position"]["side"]
                    if d1 != current_side:
                        logging.info(f"🔄 Разворот на 1м ({d1}). Закрываем {current_side}")
                        self.close_position(close_reason="exit_1m_reversal")

                # --- ЛОГИКА ВХОДА (Совпадение 1-5-30) ---
                else:
                    if d1 == d5 == d30:
                        side = "buy" if d1 == "long" else "sell"
                        logging.info(f"🎯 СОВПАДЕНИЕ 1-5-30: Входим в {side.upper()}")
                        
                        price = self.get_current_price()
                        notional = state["balance"] * POSITION_PERCENT * LEVERAGE
                        self.place_market_order(side, notional / price)
                    else:
                        # Лог для отслеживания ожидания
                        logging.debug(f"⏳ Ждем: 1м:{d1}, 5м:{d5}, 30м:{d30}")

                time.sleep(15) # Пауза между проверками
            except Exception as e:
                logging.error(f"Ошибка цикла: {e}")
                time.sleep(10)

    # ... (остальные методы place_market_order и close_position)
