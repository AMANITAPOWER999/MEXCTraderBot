import requests
import logging
import os

class SignalSender:
    """Отправка торговых сигналов GET на ngrok для ETH_USDT"""
    
    def __init__(self):
        # Жестко прописываем ваш актуальный адрес ngrok
        # Убедитесь, что эндпоинт именно /trades, как в вашем примере GET-запроса
        self.base_url = "https://traci-unflashy-questingly.ngrok-free.dev/trades"
        
        # Целевой URL для ETH_USDT Прогнозов
        self.target_url = "https://www.mexc.com/ru-RU/futures/event-futures/ETH_USDT"
        
    def send_signal(self, direction: str):
        """
        direction: 'Up' (Лонг) или 'Down' (Шорт)
        """
        # Формируем параметры в точности по вашему шаблону
        params = {
            "targetUrl": self.target_url,
            "quantity": 1,          # Поменял ставку с 5 на 1 по вашему запросу
            "timeUnit": "H1",       # Таймфрейм
            "orderDirection": direction
        }
        
        try:
            logging.info(f"🛰 Попытка отправки сигнала: {direction}")
            
            # Выполняем GET запрос
            # requests автоматически превратит params в ?targetUrl=...&quantity=1...
            response = requests.get(self.base_url, params=params, timeout=15)
            
            # Выводим полный URL в лог для проверки (можно кликнуть в консоли)
            logging.info(f"🔗 Сформированный URL: {response.url}")
            
            if response.status_code in [200, 201]:
                logging.info(f"✅ Сигнал успешно доставлен! Код: {response.status_code}")
                return True
            else:
                logging.error(f"❌ Ошибка сервера: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            logging.error(f"❌ Критическая ошибка при отправке: {e}")
            return False
    
    # Методы-триггеры
    def send_open_long(self): 
        return self.send_signal("Up")
    
    def send_open_short(self): 
        return self.send_signal("Down")

    # Для GET-схемы на «Прогнозы» закрытие обычно не используется отдельно
    def send_close_long(self): return True
    def send_close_short(self): return True
