import os
import requests
import logging
from typing import Literal

class SignalSender:
    """Отправка торговых сигналов на внешний сервис"""
    
    def __init__(self):
        # Hardcoded webhook URL (bypassing Replit Secrets issue)
        self.webhook_url = 'https://traci-unflashy-questingly.ngrok-free.dev/trade/start'
        self.auth_token = os.getenv('SIGNAL_AUTH_TOKEN', '')
        self.target_url = "https://www.mexc.com/ru-RU/futures/ETH_USDT"
        self.enabled = bool(self.webhook_url)
        
        if not self.enabled:
            logging.warning("Signal sender disabled: SIGNAL_WEBHOOK_URL not configured")
        else:
            logging.info(f"Signal sender enabled: {self.webhook_url}")
    
    def send_signal(
        self, 
        position_type: Literal["LONG", "SHORT"],
        mode: Literal["OPEN", "CLOSE"]
    ):
        """
        Отправка сигнала на внешний сервис
        
        Args:
            position_type: Тип позиции - "LONG" или "SHORT"
            mode: Режим - "OPEN" (открытие) или "CLOSE" (закрытие)
        """
        if not self.enabled:
            logging.debug(f"Signal not sent (disabled): {position_type} {mode}")
            return False
        
        # Преобразуем в правильный формат с заглавной буквы
        position_capitalized = position_type.capitalize()  # LONG -> Long, SHORT -> Short
        
        payload = {
            "settings": {
                "targetUrl": self.target_url,
                "openType": position_capitalized,
                "openPercent": 50,
                "closeType": position_capitalized,
                "closePercent": 100,
                "mode": mode
            }
        }
        
        headers = {
            "Content-Type": "application/json"
        }
        
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"
        
        try:
            logging.info(f"Sending signal: {position_type} {mode} to {self.webhook_url}")
            response = requests.post(
                self.webhook_url,
                json=payload,
                headers=headers,
                timeout=30
            )
            
            if response.status_code in [200, 201, 202]:
                logging.info(f"✅ Signal sent successfully: {position_type} {mode} (status: {response.status_code})")
                return True
            else:
                logging.error(f"❌ Signal failed: {response.status_code} - {response.text}")
                return False
                
        except requests.exceptions.Timeout:
            logging.error(f"⏱️ Signal timeout: {position_type} {mode}")
            return False
        except Exception as e:
            logging.error(f"❌ Signal error: {e}")
            return False
    
    def send_open_long(self):
        """Отправка сигнала открытия LONG позиции"""
        return self.send_signal("LONG", "OPEN")
    
    def send_close_long(self):
        """Отправка сигнала закрытия LONG позиции"""
        return self.send_signal("LONG", "CLOSE")
    
    def send_open_short(self):
        """Отправка сигнала открытия SHORT позиции"""
        return self.send_signal("SHORT", "OPEN")
    
    def send_close_short(self):
        """Отправка сигнала закрытия SHORT позиции"""
        return self.send_signal("SHORT", "CLOSE")
