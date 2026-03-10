import requests
import logging

class SignalSender:
    """Отправка торговых сигналов GET на ngrok для ETH_USDT (Ставка 5)"""
    
    def __init__(self):
        # Базовый адрес вашего сервера-моста
        self.base_url = "https://traci-unflashy-questingly.ngrok-free.dev/trades"
        
        # Целевой URL для ETH_USDT (Event Futures)
        self.target_url = "https://www.mexc.com/ru-RU/futures/event-futures/ETH_USDT"
        
    def send_signal(self, direction: str):
        """
        direction: 'Up' (Рост) или 'Down' (Падение)
        """
        # Параметры запроса согласно вашему шаблону
        params = {
            "targetUrl": self.target_url,
            "quantity": 5,          # Установлено значение 5 по вашему запросу
            "timeUnit": "M10",       # Таймфрейм 1 час
            "orderDirection": direction
        }
        
        try:
            logging.info(f"🛰 Отправка сигнала: {direction} (Сумма: 5)")
            
            # Выполнение GET запроса
            response = requests.get(self.base_url, params=params, timeout=15)
            
            # Логируем итоговую ссылку для визуальной проверки
            logging.info(f"🔗 Ссылка: {response.url}")
            
            if response.status_code in [200, 201]:
                logging.info(f"✅ Успешно доставлено. Код: {response.status_code}")
                return True
            else:
                logging.error(f"❌ Ошибка сервера: {response.status_code}")
                return False
                
        except Exception as e:
            logging.error(f"❌ Ошибка соединения: {e}")
            return False
    
    # Методы активации
    def send_open_long(self): 
        return self.send_signal("Up")
    
    def send_open_short(self): 
        return self.send_signal("Down")

    # Пустые заглушки для совместимости с логикой бота
    def send_close_long(self): return True
    def send_close_short(self): return True
