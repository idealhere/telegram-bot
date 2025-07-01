from telegram import Update, Bot
from telegram.ext import Updater, CommandHandler, CallbackContext
import ccxt
import pandas as pd
import pandas_ta as ta
import logging  # 👈 добавляем импорт логгера
import html
import time
import re
last_sent_signal = {}  # ключ: symbol, значение: 'LONG' или 'SHORT'


from flask import Flask
from threading import Thread

app = Flask('')

@app.route('/')
def home():
    return "Бот работает!"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()


# 🔧 ШАГ 1: настройка логгера
logging.basicConfig(
    filename='structure_log.txt',
    level=logging.INFO,
    format='%(asctime)s — %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# ← Вот твой встроенный токен
TOKEN = "7570443415:AAFTbFM6XoOFfSTnqo8eC3A5leB6SuKv2RY"

# Инициализируем биржу Kucoin через CCXT
exchange = ccxt.kucoin({'enableRateLimit': True})

def fetch_ohlcv(symbol='BTC/USDT', timeframe='30m', limit=100, retries=2):
    for attempt in range(retries + 1):
        try:
            data = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
            df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('timestamp', inplace=True)
            logging.info(f"✅ Данные по {symbol} получены с KuCoin (попытка {attempt + 1})")
            return df
        except Exception as e:
            logging.warning(f"⚠️ Попытка {attempt + 1} — ошибка KuCoin по {symbol}: {e}")
            time.sleep(1)

    logging.error(f"❌ Не удалось получить данные по {symbol} с KuCoin после {retries + 1} попыток")
    return pd.DataFrame()  # или raise, если хочешь, чтобы бот сигнализировал


def detect_market_structure(df):
    df['structure'] = None

    for i in range(2, len(df)):
        prev_high = df['high'].iloc[i - 1]
        prev_low = df['low'].iloc[i - 1]
        curr_high = df['high'].iloc[i]
        curr_low = df['low'].iloc[i]

        if curr_high > prev_high and curr_low > prev_low:
            df.at[df.index[i], 'structure'] = 'HH-HL'
        elif curr_high < prev_high and curr_low < prev_low:
            df.at[df.index[i], 'structure'] = 'LL-LH'
        elif curr_high > prev_high and curr_low < prev_low:
            df.at[df.index[i], 'structure'] = 'ChoCH'
        elif curr_high < prev_high and curr_low > prev_low:
            df.at[df.index[i], 'structure'] = 'BOS'

    return df

def compute_indicators(df):
    df['rsi']   = ta.rsi(df['close'], length=14)
    df['ema20'] = ta.ema(df['close'], length=20)
    df['ema50'] = ta.ema(df['close'], length=50)
    return df

def fetch_rsi_6h(symbol='BTC/USDT'):
    df = exchange.fetch_ohlcv(symbol, timeframe='6h', limit=100)
    df = pd.DataFrame(df, columns=['ts','open','high','low','close','vol'])
    df['ts'] = pd.to_datetime(df['ts'], unit='ms')
    df.set_index('ts', inplace=True)
    df['rsi'] = ta.rsi(df['close'], length=14)
    return df['rsi'].iloc[-1]




def get_signal_bar(score, emoji_passed, emoji_empty):
    return ''.join([emoji_passed] * score + [emoji_empty] * (5 - score))

def generate_report(symbol='BTC/USDT'):
    df = fetch_ohlcv(symbol=symbol)
    df = compute_indicators(df)
    last = df.iloc[-1]
    rsi_6h = fetch_rsi_6h(symbol=symbol)

    # Структура рынка по 4h
    df_struct = fetch_ohlcv(symbol=symbol, timeframe='4h')
    df_struct = detect_market_structure(df_struct)
    structure = df_struct.iloc[-1].get('structure', '—')

    # MA200 (4h)
    df_4h = fetch_ohlcv(symbol=symbol, timeframe='4h', limit=250)
    df_4h['ma200'] = df_4h['close'].rolling(window=200).mean()
    ma200_4h = df_4h['ma200'].iloc[-1]
    price_above_ma200 = last['close'] > ma200_4h

    # Заголовок
    text = (
        f"📊 {symbol}\n"
        f"🕒 {last.name.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"💰 Цена: {last['close']:.2f} USDT\n"
        f"📉 MA200 (4h): {ma200_4h:.2f} {'🟢 выше' if price_above_ma200 else '🔴 ниже'}\n"
    )

    # Условия
    long_conditions = {
        "RSI < 33": rsi_6h < 33,
        "Бычья свеча (close > open)": last['close'] > last['open'],
        "BOS (структура)": structure == 'BOS',
        "EMA20 > EMA50": last['ema20'] > last['ema50'],
        "Цена выше EMA20": last['close'] > last['ema20']
    }
    short_conditions = {
        "RSI > 67": rsi_6h > 67,
        "Медвежья свеча (close < open)": last['close'] < last['open'],
        "BOS (структура)": structure == 'BOS',
        "EMA20 < EMA50": last['ema20'] < last['ema50'],
        "Цена ниже EMA20": last['close'] < last['ema20']
    }

    long_score = sum(long_conditions.values())
    short_score = sum(short_conditions.values())

    # Фильтрация ЛОНГ-сигналов, если цена ниже MA200
    if long_score >= 3 and not price_above_ma200:
        text += "⚠️ Цена ниже MA200 — ЛОНГ-сигнал ослаблен\n"
        long_score = 0

    # Выбор направления
    if long_score > short_score:
        emoji_passed, emoji_failed, conds, score = '🟩', '⬜', long_conditions, long_score
        header = ("🟢 <b>Сигнал ЛОНГ</b>", long_score)
    else:
        emoji_passed, emoji_failed, conds, score = '🟥', '⬜', short_conditions, short_score
        header = ("🔴 <b>Сигнал ШОРТ</b>", short_score)

    # Вывод сигнала
    if score >= 3:
        text += "\n━━━━━━━━━━━━━━━━━━━━━━━\n"
        text += f"{header[0]}\n✅ Выполнено {header[1]}/5 условий:\n"
        bar = get_signal_bar(score, emoji_passed, emoji_failed)
        text += f"{bar}\n"
        for label, passed in conds.items():
            safe = html.escape(label)
            text += f"{emoji_passed if passed else emoji_failed} {safe}\n"
        text += "━━━━━━━━━━━━━━━━━━━━━━━\n"
    else:
        text += (
            f"\n⚪ <b>Пока нет точки входа</b> — "
            f"ЛОНГ: {long_score}/5, ШОРТ: {short_score}/5\n"
        )

    return text




# Telegram-бот
bot = Bot(token=TOKEN)

def start(update: Update, context: CallbackContext):
    update.message.reply_text(
        "Привет! Я бот, который присылает сигналы по BTC/USDT, ETH и SOL.\n"
        "📥 Лонг, 📤 шорт и 🟡 ранние предупреждения — только по делу.\n"
        "Используй /subscribe для подписки и /unsubscribe для отмены."
    )

def send_analysis(context: CallbackContext):
    chat_id = context.job.context
    symbols = [
        'BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'DOGE/USDT',
        'LTC/USDT', 'ADA/USDT', 'AVAX/USDT', 'UNI/USDT',
        'LINK/USDT', 'SHIB/USDT', 'ATOM/USDT'
    ]

    for symbol in symbols:
        try:
            report = generate_report(symbol=symbol)
            context.bot.send_message(chat_id=chat_id, text=report, parse_mode='HTML')
        except Exception as e:
            context.bot.send_message(chat_id=chat_id, text=f"⚠️ Ошибка при анализе {symbol}: {e}")



def send_filtered_analysis(context: CallbackContext):
    global last_sent_signal
    chat_id = context.job.context
    symbols = [
        'BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'DOGE/USDT',
        'LTC/USDT', 'ADA/USDT', 'AVAX/USDT', 'UNI/USDT',
        'LINK/USDT', 'SHIB/USDT', 'ATOM/USDT'
    ]

    sent_count = 0

    for symbol in symbols:
        try:
            report = generate_report(symbol=symbol)

            if "Сигнал ЛОНГ" in report:
                direction = 'LONG'
            elif "Сигнал ШОРТ" in report:
                direction = 'SHORT'
            else:
                continue

            match = re.search(r'Выполнено (\d+)/5', report)
            score = int(match.group(1)) if match else 0

            if score >= 4 and last_sent_signal.get(symbol) != direction:
                context.bot.send_message(chat_id=chat_id, text=report, parse_mode='HTML')
                last_sent_signal[symbol] = direction
                sent_count += 1

        except Exception as e:
            context.bot.send_message(chat_id=chat_id, text=f"⚠️ Ошибка при анализе {symbol}: {e}")

    context.bot.send_message(chat_id=chat_id, text=f"📊 Сильных сигналов отправлено: {sent_count}")



def subscribe(update: Update, context: CallbackContext):
    chat_id = update.message.chat_id
    update.message.reply_text("📬 Подписка активна!")
    context.job_queue.run_repeating(
        send_filtered_analysis,
        interval=1800,
        first=5,
        context=chat_id,
        name=str(chat_id)
    )

def unsubscribe(update: Update, context: CallbackContext):
    chat_id = update.message.chat_id
    jobs = context.job_queue.get_jobs_by_name(str(chat_id))
    for job in jobs:
        job.schedule_removal()
    update.message.reply_text("❌ Подписка отменена.")

def main():
    updater = Updater(token=TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("subscribe", subscribe))
    dp.add_handler(CommandHandler("unsubscribe", unsubscribe))

    keep_alive()
    updater.start_polling()
    updater.idle()



if __name__ == "__main__":
    main()
