import os
import logging
import requests
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

class TelegramBotHandler:
    def __init__(self):
        self.bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
        self.chat_id = os.getenv('TELEGRAM_CHAT_ID')
        
        if not self.bot_token:
            logging.error("TELEGRAM_BOT_TOKEN not set")
            return
        
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}"
        logging.info("Telegram bot handler initialized")
    
    def setup_webapp_button(self):
        """Настройка кнопки WebApp в меню бота"""
        if not self.bot_token:
            logging.error("Cannot setup WebApp: bot token not configured")
            return False
        
        try:
            # --- ИЗМЕНЕННЫЙ УЧАСТОК КОДА ---
            # Явное указание нового домена Railway
            BASE_DOMAIN = "https://arbitragebotv20-pocketoptionbotv10.up.railway.app"
            webapp_url = f"{BASE_DOMAIN}/webapp"
            
            # Удаляем старую логику определения домена Replit
            # replit_domain = os.getenv('REPL_SLUG', 'goldantelopebtcx500')
            # replit_user = os.getenv('REPL_OWNER', 'your-username')
            # webapp_url = f"https://{replit_domain}.{replit_user}.repl.co/webapp"
            
            # env_domain = os.popen('env | grep DOMAIN').read()
            # if 'REPLIT_DEV_DOMAIN' in env_domain:
            #     domain = env_domain.split('REPLIT_DEV_DOMAIN=')[1].split('\n')[0]
            #     webapp_url = f"https://{domain}/webapp"
            # -------------------------------
            
            logging.info(f"WebApp URL: {webapp_url}")
            
            # Устанавливаем команды бота
            commands = [
                {
                    "command": "start",
                    "description": "🚀 Open Trading Dashboard"
                },
                {
                    "command": "status",
                    "description": "📊 Get current status"
                }
            ]
            
            commands_response = requests.post(
                f"{self.base_url}/setMyCommands",
                json={"commands": commands},
                timeout=10
            )
            
            if commands_response.status_code == 200:
                logging.info("✅ Bot commands configured successfully")
            else:
                logging.error(f"Failed to set commands: {commands_response.text}")
            
            # Устанавливаем кнопку меню с WebApp
            menu_button = {
                "type": "web_app",
                "text": "🚀 Open Dashboard",
                "web_app": {
                    "url": webapp_url
                }
            }
            
            menu_response = requests.post(
                f"{self.base_url}/setChatMenuButton",
                json={"menu_button": menu_button},
                timeout=10
            )
            
            if menu_response.status_code == 200:
                logging.info("✅ WebApp menu button configured successfully")
                logging.info(f"    WebApp URL: {webapp_url}")
                return True
            else:
                logging.error(f"Failed to set menu button: {menu_response.text}")
                return False
            
        except Exception as e:
            logging.error(f"Error setting up WebApp button: {e}")
            return False
    
    def send_welcome_message(self):
        """Отправляет приветственное сообщение с инструкциями"""
        if not self.bot_token or not self.chat_id:
            return
        
        try:
            # Заменяем старое название проекта на общее
            message = (
                "🚀 <b>Trading Bot Dashboard</b>\n\n"
                "Welcome! Your Telegram mini app is ready.\n\n"
                "📱 <b>How to use:</b>\n"
                "• Click the menu button (☰) at the bottom\n"
                "• Select '🚀 Open Dashboard'\n"
                "• Control your trading bot from Telegram!\n\n"
                "💡 You can also use:\n"
                "/start - Open the WebApp\n"
                "/status - Get current bot status"
            )
            
            response = requests.post(
                f"{self.base_url}/sendMessage",
                json={
                    "chat_id": self.chat_id,
                    "text": message,
                    "parse_mode": "HTML"
                },
                timeout=10
            )
            
            if response.status_code == 200:
                logging.info("✅ Welcome message sent")
            else:
                logging.error(f"Failed to send welcome message: {response.text}")
        
        except Exception as e:
            logging.error(f"Error sending welcome message: {e}")

def setup_telegram_webapp():
    """Основная функция для настройки Telegram WebApp"""
    handler = TelegramBotHandler()
    
    if handler.bot_token:
        logging.info("Setting up Telegram WebApp...")
        success = handler.setup_webapp_button()
        
        if success:
            handler.send_welcome_message()
            logging.info("✅ Telegram WebApp setup complete!")
        else:
            logging.error("❌ Failed to setup Telegram WebApp")
    else:
        logging.warning("⚠️ Telegram bot token not configured. Skipping WebApp setup.")

if __name__ == "__main__":
    setup_telegram_webapp()
