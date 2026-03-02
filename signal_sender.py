cat <<EOF > signal_sender.py
import requests
import logging
import os

class SignalSender:
    def __init__(self):
        # Берем URL из переменных окружения, если его нет - используем localhost
        self.url = os.getenv("SIGNAL_WEBHOOK_URL", "http://localhost:5000/trade/start")
        self.target_url = "https://www.mexc.com/ru-RU/futures/SOL_USDT"
        
    def send_signal(self, side: str, mode: str):
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
            logging.info(f"Response: {response.status_code}")
            return response.status_code in [200, 201]
        except Exception as e:
            logging.error(f"Signal Error: {e}")
            return False

    def send_open_long(self): return self.send_signal("Long", "OPEN")
    def send_close_long(self): return self.send_signal("Long", "CLOSE")
    def send_open_short(self): return self.send_signal("Short", "OPEN")
    def send_close_short(self): return self.send_signal("Short", "CLOSE")
EOF
