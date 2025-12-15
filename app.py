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

# ================== ENV ==================
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

app = Flask(__name__)

SESSION_SECRET = os.getenv('SESSION_SECRET') or secrets.token_hex(32)
app.secret_key = SESSION_SECRET

# ================== GLOBALS ==================
bot_instance = None
bot_thread = None
bot_running = False
telegram_notifier = None


# ================== TELEGRAM ==================
def init_telegram():
    global telegram_notifier

    bot_token = os.getenv('TELEGRAM_BOT_TOKEN', '')
    chat_id = os.getenv('TELEGRAM_CHAT_ID', '')

    if bot_token and chat_id:
        telegram_notifier = TelegramNotifier(bot_token, chat_id)
        logging.info("Telegram notifier initialized")
    else:
        telegram_notifier = None
        logging.warning("Telegram credentials not configured")


# ================== BOT LOOP ==================
def bot_main_loop():
    global bot_running, bot_instance

    try:
        bot_instance = TradingBot(telegram_notifier=telegram_notifier)
        logging.info("Trading bot initialized")

        def should_continue():
            return bot_running

        bot_instance.strategy_loop(should_continue=should_continue)
    except Exception as e:
        logging.exception("Bot crashed")
        bot_running = False


# ================== ROUTES ==================
@app.route('/')
def index():
    return render_template('dashboard.html')


@app.route('/webapp')
def webapp():
    return render_template('webapp.html')


# 🔴 ИСПРАВЛЕНО — БОЛЬШЕ НЕ ДАЕТ 500
@app.route('/api/status')
def api_status():
    try:
        directions = {}
        current_price = 3000.0

        if bot_instance and bot_running:
            try:
                directions = bot_instance.get_current_directions()
            except Exception as e:
                logging.warning(f"SAR unavailable: {e}")

            try:
                current_price = bot_instance.get_current_price()
            except Exception as e:
                logging.warning(f"Price unavailable: {e}")

        return jsonify({
            'bot_running': bot_running,
            'paper_mode': os.getenv('RUN_IN_PAPER', '1') == '1',
            'balance': state.get('balance', 100.0),
            'available': state.get('available', 100.0),
            'in_position': state.get('in_position', False),
            'position': state.get('position'),
            'current_price': current_price,
            'directions': directions,
            'sar_directions': directions,
            'trades': state.get('trades', [])
        })

    except Exception as e:
        logging.exception("STATUS ERROR")
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

    if not bot_running:
        return jsonify({'error': 'Bot not running'}), 400

    bot_running = False
    logging.info("Bot stopped")
    return jsonify({'status': 'stopped'})


@app.route('/api/close_position', methods=['POST'])
def api_close_position():
    if not state.get('in_position'):
        return jsonify({'error': 'No open position'}), 400

    try:
        trade = bot_instance.close_position(close_reason='manual')
        return jsonify({'trade': trade})
    except Exception as e:
        logging.exception("Close position error")
        return jsonify({'error': str(e)}), 500


@app.route('/api/reset_balance', methods=['POST'])
def api_reset_balance():
    state['balance'] = 100.0
    state['available'] = 100.0
    state['in_position'] = False
    state['position'] = None
    state['trades'] = []
    state.pop('telegram_trade_counter', None)

    if bot_instance:
        bot_instance.save_state_to_file()

    logging.info("Balance reset")
    return jsonify({'balance': 100.0})


@app.route('/api/send_test_message', methods=['POST'])
def api_send_test_message():
    if not telegram_notifier:
        return jsonify({'error': 'Telegram not configured'}), 400

    msg = (
        "🤖 <b>Test message</b>\n\n"
        f"Time: {datetime.utcnow().strftime('%H:%M:%S UTC')}\n"
        f"Balance: ${state.get('balance', 0):.2f}"
    )

    telegram_notifier.send_message(msg)
    return jsonify({'status': 'sent'})


# ================== INIT ==================
init_telegram()

try:
    from telegram_bot_handler import setup_telegram_webapp
    setup_telegram_webapp()
except Exception as e:
    logging.warning(f"Telegram WebApp not setup: {e}")


# ================== MAIN ==================
if __name__ == '__main__':
    port = int(os.getenv('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False)
