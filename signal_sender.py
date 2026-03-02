import requests
import logging

class SignalSender:
    """Отправка торговых сигналов через POST JSON на локальный сервер"""
    
    def __init__(self):
        # Актуальный URL для POST запросов
        self.url = "http://localhost:5000/trade/start"
        # Базовый URL ассета на MEXC
        self.target_url = "https://www.mexc.com/ru-RU/futures/SOL_USDT"
        
    def send_signal(self, side: str, mode: str):
        """
         side: 'Long' или 'Short'
         mode: 'OPEN' или 'CLOSE'
        """
        payload = {
            "settings": {
                "targetUrl": self.target_url,
                "openType": side,
                "openPercent": 20,
                "closeType": side,
                "closePercent": 100,
                "mode": mode
            }
        }
        
        try:
            logging.info(f"Sending POST to {self.url} | {side} {mode}")
            response = requests.post(self.url, json=payload, timeout=10)
            
            if response.status_code in [200, 201]:
                logging.info(f"✅ Успешно отправлено: {response.status_code}")
                return True
            else:
                logging.error(f"❌ Ошибка сервера: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            logging.error(f"❌ Ошибка подключения: {e}")
            return False
    
    # Методы управления позициями
    def send_open_long(self):
        return self.send_signal("Long", "OPEN")
    
    def send_close_long(self):
        return self.send_signal("Long", "CLOSE")
    
    def send_open_short(self):
        return self.send_signal("Short", "OPEN")
    
    def send_close_short(self):
        return self.send_signal("Short", "CLOSE")
