import requests
import logging
import os

class SignalSender:
    """Отправка торговых сигналов (GET) для фьючерсных прогнозов MEXC"""
    
    def __init__(self):
        # Базовый адрес сервера (локальный или из переменной окружения)
        self.base_url = os.getenv("SIGNAL_WEBHOOK_URL", "http://localhost:5000/trades")
        # URL целевого актива на MEXC (Event Futures)
        self.target_url = "https://www.mexc.com/ru-RU/futures/event-futures/ETH_USDT"
        
    def send_signal(self, direction: str):
        """
        direction: 'Up' (для лонга/роста) или 'Down' (для шорта/падения)
        """
        # Формируем параметры запроса
        params = {
            "targetUrl": self.target_url,
            "quantity": 5,      # Ваша текущая ставка
            "timeUnit": "H1",   # Таймфрейм 1 час
            "orderDirection": direction
        }
        
        try:
            logging.info(f"🚀 Sending GET signal to {self.base_url} | Direction: {direction}")
            
            # Отправка GET запроса с параметрами
            response = requests.get(self.base_url, params=params, timeout=10)
            
            # Логируем итоговый URL для проверки
            logging.debug(f"🔗 Full URL: {response.url}")
            
            if response.status_code in [200, 201]:
                logging.info(f"✅ Signal Success: {response.status_code}")
                return True
            else:
                logging.error(f"❌ Server Error: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            logging.error(f"❌ Connection Failed: {e}")
            return False
    
    # Методы управления (только на открытие, согласно ТЗ)
    def send_open_long(self): 
        return self.send_signal("Up")
    
    def send_open_short(self): 
        return self.send_signal("Down")

    # Методы закрытия (если потребуются, сейчас возвращают False или можно оставить пустыми)
    def send_close_long(self):
        logging.warning("⚠️ Close signal not implemented for GET mode")
        return False

    def send_close_short(self):
        logging.warning("⚠️ Close signal not implemented for GET mode")
        return False
