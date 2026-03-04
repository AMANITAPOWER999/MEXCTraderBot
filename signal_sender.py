import requests
import logging

class SignalSender:
    """
    Отправка торговых сигналов на сервер-мост (JSON формат)
    """

    def __init__(self):
        # URL куда отправляем сигнал
        self.base_url = "https://traci-unflashy-questingly.ngrok-free.dev/trades"

        # Торговая пара
        self.target_url = "https://www.mexc.com/ru-RU/futures/SOL_USDT"

        # Процент входа
        self.open_percent = 20
        self.close_percent = 100

    def _send(self, open_type: str, mode: str):
        payload = {
            "settings": {
                "targetUrl": self.target_url,
                "openType": open_type,       # Long / Short
                "openPercent": self.open_percent,
                "closeType": open_type,
                "closePercent": self.close_percent,
                "mode": mode                 # OPEN / CLOSE
            }
        }

        try:
            logging.info(f"📡 Отправка сигнала: {open_type} {mode}")
            logging.info(f"📦 Payload: {payload}")

            response = requests.post(
                self.base_url,
                json=payload,
                timeout=15
            )

            if response.status_code in (200, 201):
                logging.info(f"✅ Сигнал отправлен успешно ({response.status_code})")
                return True
            else:
                logging.error(f"❌ Ошибка ответа сервера: {response.status_code}")
                logging.error(response.text)
                return False

        except Exception as e:
            logging.error(f"❌ Ошибка отправки сигнала: {e}")
            return False

    # ====== ОТКРЫТИЕ ======
    def send_open_long(self):
        return self._send("Long", "OPEN")

    def send_open_short(self):
        return self._send("Short", "OPEN")

    # ====== ЗАКРЫТИЕ ======
    def send_close_long(self):
        return self._send("Long", "CLOSE")

    def send_close_short(self):
        return self._send("Short", "CLOSE")
