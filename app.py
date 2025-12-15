import os
import logging
import secrets
from dotenv import load_dotenv
from flask import Flask, render_template, jsonify, request
import threading
from datetime import datetime
import pandas as pd

from trading_bot import TradingBot, state
from telegram_notifications import TelegramNotifier

# -------------------------------
# ENV + LOGGING
# -------------------------------
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

app = Flask(__name__)

SESSION_SECRET = os.getenv('SESSION_SECRET')
if not SESSION_SECRET:
    SESSION_SECRET = secrets.token_hex(32)
    logging.warning("⚠️ SESSION_SECRET not set, generated temporary key")

app.secret_key = SESSION_SECRET

# -------------------------------
# GLOBALS
# -------------------------------
bot_instance = None
bot_thread = None
bot_running = False
telegram_notifier = None

# -------------------------------
# TELEGRAM
# -------------------------------
def init_telegram():
    global telegram_notifier

    bot_token = os.getenv('TELEGRAM_BOT_TOKEN', '')
    chat_id = os.getenv('TELEGRAM_CHAT_ID', '')

    if bot_token and chat_id:
        telegram_notifier = TelegramNotifier(bot_token, chat_id)
        logging.info("Telegram notifier initialized")
    else:
        logging.warning("Telegram credentials not configured")

# -------------------------------
# BOT THREAD
# -------------------------------
def bot_main_loop():
    global bot_instance, bot_running

    try:
        bot_instance = TradingBot(telegram_notifier=telegram_notifier)
        logging.info("Trading bot initialized")

        # ⚠️ ВАЖНО: без аргументов
        bot_instance.strategy_loop()

    except Exception as e:
        logging.exception("Bot crashed")
    finally:
        bot_running = False

# -------------------------------
# ROUTES
# -------------------------------
@app.route('/')
def index():
    return render_template('dashboard.html')

@app.route('/webapp')
def webapp():
    return render_template('webapp.html')

@app.route('/api/status')
def api_status():
    try:
        directions = bot_instance.get_current_directions() if bot_instance else {}

        return jsonify({
            'bot_running': bot_running,
            'paper_mode': os.getenv('RUN_IN_PAPER', '1') == '1',
            'balance': state.get('balance', 1000),
            'available': state.get('available', 1000),
            'in_position': state.get('in_position', False),
            'position': state.get('position'),
            'current_price': bot_instance.get_current_price() if bot_instance else 0,
            'directions': directions,
            'sar_directions': directions,
            'trades': state.get('trades', [])
        })
    except Exception as e:
        logging.error(f"Status error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/start_bot', methods=['POST'])
def api_start_bot():
    global bot_running, bot_thread

    if bot_running:
        return jsonify({'error': 'Bot already running'}), 400

    bot_running = True
    bot_thread = threading.Thread(target=bot_main_loop, daemon=True)
    bot_thread.start()

    logging.info("Bot started")
    return jsonify({'status': 'running'})

@app.route('/api/stop_bot', methods=['POST'])
def api_stop_bot():
    global bot_running
    bot_running = False
    logging.info("Bot stopped")
    return jsonify({'status': 'stopped'})

@app.route('/api/reset_balance', methods=['POST'])
def api_reset_balance():
    state['balance'] = 100.0
    state['available'] = 100.0
    state['in_position'] = False
    state['position'] = None
    state['trades'] = []

    if bot_instance:
        bot_instance.save_state_to_file()

    logging.info("Balance reset")
    return jsonify({'balance': 100})

@app.route('/api/debug_sar')
def api_debug_sar():
    if not bot_instance:
        return jsonify({'error': 'Bot not running'}), 400

    data = {}
    for tf in ['1m', '5m', '15m']:
        df = bot_instance.fetch_ohlcv_tf(tf, limit=50)
        if df is None or df.empty:
            continue

        psar = bot_instance.compute_psar(df)
        direction = bot_instance.get_direction_from_psar(df)

        data[tf] = {
            'direction': direction,
            'close': float(df['close'].iloc[-1]),
            'psar': float(psar.iloc[-1])
        }

    return jsonify(data)

# -------------------------------
# INIT
# -------------------------------
init_telegram()

try:
    from telegram_bot_handler import setup_telegram_webapp
    setup_telegram_webapp()
except Exception as e:
    logging.error(f"Telegram WebApp setup failed: {e}")

# -------------------------------
# RUN
# -------------------------------
if __name__ == '__main__':
    port = int(os.getenv('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False)
