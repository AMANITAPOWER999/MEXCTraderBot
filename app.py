import os
import logging
import secrets
from dotenv import load_dotenv
from flask import Flask, render_template, jsonify, request, session, redirect, url_for
import threading
from datetime import datetime
import pandas as pd
from trading_bot import TradingBot, state
from telegram_notifications import TelegramNotifier

# Загружаем переменные окружения из .env файла
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

app = Flask(__name__)

# Генерируем безопасный случайный ключ если SESSION_SECRET не установлен
SESSION_SECRET = os.getenv('SESSION_SECRET')
if not SESSION_SECRET:
    SESSION_SECRET = secrets.token_hex(32)
    logging.warning("⚠️  SESSION_SECRET не установлен! Используется случайно сгенерированный ключ. Установите SESSION_SECRET в секретах для постоянства сессий между перезапусками.")

app.secret_key = SESSION_SECRET

# Глобальные переменные
bot_instance = None
bot_thread = None
bot_running = False
telegram_notifier = None

def init_telegram():
    """Инициализация Telegram уведомлений"""
    global telegram_notifier
    
    bot_token = os.getenv('TELEGRAM_BOT_TOKEN', '')
    chat_id = os.getenv('TELEGRAM_CHAT_ID', '')
    
    if bot_token and chat_id:
        telegram_notifier = TelegramNotifier(bot_token, chat_id)
        logging.info("Telegram notifier initialized")
    else:
        logging.warning("Telegram credentials not configured")

def bot_main_loop():
    """Основной цикл торгового бота"""
    global bot_running, bot_instance
    
    try:
        bot_instance = TradingBot(telegram_notifier=telegram_notifier)
        logging.info("Trading bot initialized")
        
        def should_continue():
            return bot_running
        
        bot_instance.strategy_loop(should_continue=should_continue)
    except Exception as e:
        logging.error(f"Bot error: {e}")
        bot_running = False

@app.route('/')
def index():
    """Главная страница - дашборд"""
    return render_template('dashboard.html')

@app.route('/webapp')
def webapp():
    """Telegram WebApp интерфейс"""
    return render_template('webapp.html')

@app.route('/api/status')
def api_status():
    """Получение текущего статуса бота"""
    try:
        # Получаем текущие направления SAR
        directions = {}
        # Получаем текущую цену
        current_price = 3000.0

        if bot_instance:
            directions = bot_instance.get_current_directions()
            current_price = bot_instance.get_current_price()
        
        # Получаем номер последней сделки для отображения
        trade_counter = state.get('telegram_trade_counter', 0)
        # Если сделка в позиции, берем ее номер. Иначе - последний закрытый номер.
        if state.get('in_position') and state.get('position'):
            current_trade_number = state['position'].get('trade_number', trade_counter + 1)
        else:
            current_trade_number = trade_counter
        

        return jsonify({
            'bot_running': bot_running,
            'paper_mode': os.getenv('RUN_IN_PAPER', '1') == '1',
            'balance': state.get('balance', 1000),
            'available': state.get('available', 1000),
            'in_position': state.get('in_position', False),
            'position': state.get('position'),
            'current_price': current_price,
            'directions': directions,
            'sar_directions': directions,
            'trades': state.get('trades', []),
            'current_trade_number': current_trade_number # Добавлено для отображения в дашборде
        })
    except Exception as e:
        logging.error(f"Status error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/start_bot', methods=['POST'])
def api_start_bot():
    """Запуск торгового бота"""
    global bot_running, bot_thread
    
    if bot_running:
        return jsonify({'error': 'Бот уже запущен'}), 400
    
    try:
        bot_running = True
        bot_thread = threading.Thread(target=bot_main_loop, daemon=True)
        bot_thread.start()
        
        logging.info("Trading bot started")
        return jsonify({'message': 'Бот успешно запущен', 'status': 'running'})
    except Exception as e:
        bot_running = False
        logging.error(f"Start bot error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/stop_bot', methods=['POST'])
def api_stop_bot():
    """Остановка торгового бота"""
    global bot_running
    
    if not bot_running:
        return jsonify({'error': 'Бот уже остановлен'}), 400
    
    try:
        bot_running = False
        # Добавляем паузу, чтобы поток успел завершиться после остановки
        time.sleep(2) 
        logging.info("Trading bot stopped")
        return jsonify({'message': 'Бот успешно остановлен', 'status': 'stopped'})
    except Exception as e:
        logging.error(f"Stop bot error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/close_position', methods=['POST'])
def api_close_position():
    """Принудительное закрытие позиции"""
    if not state.get('in_position'):
        return jsonify({'error': 'Нет открытой позиции'}), 400
    
    try:
        if bot_instance:
            trade = bot_instance.close_position(close_reason='manual')
            if trade:
                return jsonify({'message': 'Позиция успешно закрыта', 'trade': trade})
            else:
                return jsonify({'error': 'Ошибка закрытия позиции'}), 500
        else:
            return jsonify({'error': 'Бот не инициализирован'}), 500
    except Exception as e:
        logging.error(f"Close position error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/send_test_message', methods=['POST'])
def api_send_test_message():
    """Отправка тестового сообщения в Telegram"""
    if not telegram_notifier:
        return jsonify({'error': 'Telegram не настроен'}), 400
    
    try:
        message = f"""
🤖 <b>Тестовое уведомление</b>

Бот работает корректно и готов к отправке уведомлений!

⏰ Время: {datetime.utcnow().strftime("%H:%M:%S UTC")}
💰 Баланс: ${state.get('balance', 0):.2f}
        """.strip()
        
        success = telegram_notifier.send_message(message)
        if success:
            return jsonify({'message': 'Тестовое сообщение отправлено в Telegram'})
        else:
            return jsonify({'error': 'Ошибка отправки сообщения'}), 500
    except Exception as e:
        logging.error(f"Test message error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/telegram_info')
def api_telegram_info():
    """Получение информации о Telegram боте"""
    owner_id = os.getenv('TELEGRAM_OWNER_ID', 'NOT_SET')
    
    webhook_status = 'not_set'
    if telegram_notifier and telegram_notifier.bot_token:
        webhook_status = 'configured'
    
    return jsonify({
        'owner_id': owner_id,
        'webhook_status': webhook_status,
        'bot_configured': telegram_notifier is not None
    })

@app.route('/api/debug_sar')
def api_debug_sar():
    """Получение отладочной информации о SAR индикаторе"""
    if not bot_instance:
        return jsonify({'error': 'Бот не инициализирован'}), 500
    
    try:
        debug_data = {
            'timestamp': datetime.utcnow().isoformat(),
            'current_price': bot_instance.get_current_price(),
            'sar_data': {}
        }
        
        for tf in ['15m', '5m', '1m']:
            df = bot_instance.fetch_ohlcv_tf(tf, limit=50)
            if df is not None and len(df) > 0:
                psar = bot_instance.compute_psar(df)
                direction = bot_instance.get_direction_from_psar(df)
                
                last_close = df['close'].iloc[-1]
                last_psar = psar.iloc[-1] if psar is not None else 0
                
                debug_data['sar_data'][tf] = {
                    'direction': direction,
                    'last_close': f"{last_close:.2f}",
                    'last_psar': f"{last_psar:.2f}",
                    'close_vs_psar': f"{(last_close - last_psar):.2f}",
                    'last_candles': [
                        {
                            'time': pd.to_datetime(row['datetime']).strftime('%H:%M'),
                            'open': f"{row['open']:.2f}",
                            'high': f"{row['high']:.2f}",
                            'low': f"{row['low']:.2f}",
                            'close': f"{row['close']:.2f}"
                        }
                        for _, row in df.tail(5).iterrows()
                    ]
                }
            else:
                debug_data['sar_data'][tf] = {'error': 'No data'}
        
        return jsonify(debug_data)
    except Exception as e:
        logging.error(f"Debug SAR error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/get_global_state')
def api_get_global_state():
    """Получение глобального состояния для Telegram бота"""
    return jsonify({
        'bot_running': bot_running,
        'balance': state.get('balance', 1000),
        'available': state.get('available', 1000),
        'in_position': state.get('in_position', False),
        'current_price': bot_instance.get_current_price() if bot_instance else 3000.0
    })

@app.route('/api/chart_data')
def api_chart_data():
    """Get 1m chart data with entry/exit markers"""
    try:
        # Return empty data if bot not running
        if not bot_instance:
            return jsonify({
                'candles': [],
                'markers': []
            })
        
        # Get last 50 candles (50 minutes of 1m data) for larger candlesticks
        df = bot_instance.fetch_ohlcv_tf('1m', limit=50)
        
        if df is None or len(df) == 0:
            return jsonify({
                'candles': [],
                'markers': []
            })
        
        # Prepare candle data
        candles = []
        for _, row in df.iterrows():
            candles.append({
                'time': pd.to_datetime(row['datetime']).strftime('%H:%M'),
                'open': float(row['open']),
                'high': float(row['high']),
                'low': float(row['low']),
                'close': float(row['close'])
            })
        
        # Get trade markers (entry/exit points)
        # Match by time string (HH:MM) instead of exact timestamp
        markers = []
        recent_trades = state.get('trades', [])[-20:]  # Last 20 trades
        
        for trade in recent_trades:
            # Try different field names for entry time
            entry_time_str = trade.get('entry_time') or trade.get('time')
            if entry_time_str:
                entry_time = datetime.fromisoformat(entry_time_str)
                
                # Entry marker - use time string for matching
                markers.append({
                    'time': entry_time.strftime('%H:%M'),
                    'price': trade.get('entry_price', trade.get('price', 0)),
                    'type': 'entry',
                    'side': trade.get('side', 'long')
                })
                
                # Exit marker
                exit_time_str = trade.get('time')
                if exit_time_str: # In current state, 'time' holds exit time
                    exit_time = datetime.fromisoformat(exit_time_str)
                    markers.append({
                        'time': exit_time.strftime('%H:%M'),
                        'price': trade.get('exit_price', 0),
                        'type': 'exit',
                        'side': trade.get('side', 'long')
                    })
        
        # Current position marker
        if state.get('in_position') and state.get('position'):
            pos = state['position']
            entry_time_str = pos.get('entry_time')
            if entry_time_str:
                entry_time = datetime.fromisoformat(entry_time_str)
                markers.append({
                    'time': entry_time.strftime('%H:%M'),
                    'price': pos.get('entry_price', 0),
                    'type': 'entry',
                    'side': pos.get('side', 'long'),
                    'current': True
                })
        
        return jsonify({
            'candles': candles,
            'markers': markers
        })
    except Exception as e:
        logging.error(f"Chart data error: {e}")
        return jsonify({
            'candles': [],
            'markers': []
        })

@app.route('/api/delete_last_trade', methods=['POST'])
def api_delete_last_trade():
    """Delete the last trade from history"""
    try:
        trades = state.get('trades', [])
        if len(trades) == 0:
            return jsonify({'error': 'No trades to delete'}), 400
        
        deleted_trade = trades.pop(0) # Удаляем самую последнюю (самую верхнюю) сделку
        state['trades'] = trades
        
        # Обновляем счетчик сделок, чтобы он соответствовал последнему номеру
        if 'telegram_trade_counter' in state:
            state['telegram_trade_counter'] = state.get('telegram_trade_counter', 1) - 1
            if state['telegram_trade_counter'] < 0:
                 state['telegram_trade_counter'] = 0

        # Save state
        if bot_instance:
            bot_instance.save_state_to_file()
        
        logging.info(f"Deleted last trade: {deleted_trade}")
        return jsonify({'message': 'Last trade deleted successfully', 'deleted_trade': deleted_trade})
    except Exception as e:
        logging.error(f"Delete trade error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/reset_balance', methods=['POST'])
def api_reset_balance():
    """Reset balance to $100 and reset trade counter"""
    try:
        START_BANK = 100.0 # Используем фиксированную сумму, как в trading_bot
        state['balance'] = START_BANK
        state['available'] = START_BANK
        state['in_position'] = False
        state['position'] = None
        state['trades'] = []
        # Reset trade counter to 0 (next trade will be number 1)
        state['telegram_trade_counter'] = 0
        
        # Save state
        if bot_instance:
            bot_instance.save_state_to_file()
        
        logging.info("Balance reset to $100 and trade counter reset")
        return jsonify({'message': 'Balance reset to $100, trades cleared, counter reset', 'balance': START_BANK})
    except Exception as e:
        logging.error(f"Reset balance error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/send_current_position', methods=['POST'])
def api_send_current_position():
    """Send current position to Telegram"""
    try:
        if not telegram_notifier:
            return jsonify({'error': 'Telegram not configured'}), 400
        
        if not bot_instance:
            return jsonify({'error': 'Бот не инициализирован'}), 500

        current_price = bot_instance.get_current_price()
        position = state.get('position')
        balance = state.get('balance', 0)
        
        telegram_notifier.send_current_position(position, current_price, balance)
        
        logging.info("Current position sent to Telegram")
        return jsonify({'message': 'Current position sent to Telegram successfully'})
    except Exception as e:
        logging.error(f"Send position error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/verify_password', methods=['POST'])
def api_verify_password():
    """Verify dashboard password"""
    try:
        data = request.get_json()
        password = data.get('password', '')
        
        dashboard_password = os.getenv('DASHBOARD_PASSWORD', '')
        
        if not dashboard_password:
            # If no password is set, allow access
            return jsonify({'success': True})
        
        if password == dashboard_password:
            return jsonify({'success': True})
        else:
            return jsonify({'success': False})
    except Exception as e:
        logging.error(f"Password verification error: {e}")
        return jsonify({'success': False}), 500

@app.route('/webhook/telegram', methods=['POST'])
def telegram_webhook():
    """Webhook для Telegram бота"""
    if not telegram_notifier:
        return 'OK', 200
    
    try:
        update = request.get_json()
        if update and 'message' in update:
            telegram_notifier.handle_message(update['message'])
    except Exception as e:
        logging.error(f"Telegram webhook error: {e}")
    
    return 'OK', 200

# Инициализация Telegram при загрузке модуля
init_telegram()

# Настройка Telegram WebApp
try:
    from telegram_bot_handler import setup_telegram_webapp
    setup_telegram_webapp()
except Exception as e:
    logging.error(f"Failed to setup Telegram WebApp: {e}")

if __name__ == '__main__':
    # Запуск Flask приложения
    port = int(os.getenv('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False)
