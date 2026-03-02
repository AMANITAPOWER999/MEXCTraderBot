import requests
import logging

class SignalSender:
    """Отправка торговых сигналов на внешний сервис через ngrok (GET)"""
    
    def __init__(self):
        # Актуальный URL для GET запросов через ngrok
        self.base_url = "https://traci-unflashy-questingly.ngrok-free.dev/trades"
        self.target_url = "https://www.mexc.com/ru-RU/futures/prediction-futures/ETH_USDT"
        
    def send_signal(self, order_direction: str):
        """
        Отправка GET вебхука с параметрами в URL
        order_direction: 'Up' или 'Down'
        """
        params = {
            "targetUrl": self.target_url,
            "quantity": 5,
            "timeUnit": "M10",
            "orderDirection": order_direction
        }
        
        # Localhost URL as requested by user
        local_url = "http://localhost:5000/trades"
        
        try:
            # First try localhost
            logging.info(f"Sending GET webhook to {local_url} with params: {params}")
            response = requests.get(local_url, params=params, timeout=15)
            logging.info(f"Local webhook response: {response.status_code}")
            
            # Then try ngrok
            logging.info(f"Sending GET webhook to {self.base_url} with params: {params}")
            response_ngrok = requests.get(self.base_url, params=params, timeout=15)
            logging.info(f"Ngrok webhook response: {response_ngrok.status_code}")
            
            return True
        except Exception as e:
            logging.error(f"Failed to send webhook: {e}")
            return False
    
    def send_open_long(self):
        """Отправка сигнала открытия LONG (Up)"""
        return self.send_signal("Up")
    
    def send_close_long(self):
        """Закрытие лонга (теперь не отправляем отдельный сигнал или отправляем специфичный, 
        но по запросу пользователя только Up/Down при открытии/шорте)
        Пользователь указал только два типа ссылок. 
        Вероятно, закрытие не требуется или дублирует логику.
        Оставим заглушку, чтобы не ломать TradingBot.
        """
        logging.info("Close long signal skipped (as per new instructions)")
        return True
    
    def send_open_short(self):
        """Отправка сигнала открытия SHORT (Down)"""
        return self.send_signal("Down")
    
    def send_close_short(self):
        """Закрытие шорта - заглушка"""
        logging.info("Close short signal skipped (as per new instructions)")
        return True
