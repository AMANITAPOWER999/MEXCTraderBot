import requests
import logging
import os

class SignalSender:
    """Отправка торговых сигналов (POST JSON) на внешний сервис через ngrok или локально"""
    
    def __init__(self):
        # Приоритет: переменная SIGNAL_WEBHOOK_URL в Railway, иначе localhost
        self.url = os.getenv("SIGNAL_WEBHOOK_URL", "http://localhost:5000/trade/start")
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
            logging.info(f"🚀 Sending POST to {self.url} | {side} {mode}")
            
            # Отправка JSON запроса
            response = requests.post(self.url, json=payload, timeout=10)
            
            if response.status_code in [200, 201]:
                logging.info(f"✅ Webhook Success: {response.status_code}")
                return True
            else:
                logging.error(f"❌ Webhook Server Error: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            logging.error(f"❌ Webhook Connection Failed: {e}")
            return False
    
    # Методы управления сигналами для TradingBot
    def send_open_long(self): 
        return self.send_signal("Long", "OPEN")
    
    def send_close_long(self): 
        return self.send_signal("Long", "CLOSE")
    
    def send_open_short(self): 
        return self.send_signal("Short", "OPEN")
    
    def send_close_short(self): 
        return self.send_signal("Short", "CLOSE")
