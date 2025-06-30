from telegram import Update, Bot
from telegram.ext import Updater, CommandHandler, CallbackContext
import ccxt
import pandas as pd
import pandas_ta as ta
import logging  # 👈 добавляем импорт логгера

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

def fetch_ohlcv(symbol='BTC/USDT', timeframe='30m', limit=100):
    data = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
    df = pd.DataFrame(data, columns=['ts','open','high','low','close','vol'])
    df['ts'] = pd.to_datetime(df['ts'], unit='ms')
    return df.set_index('ts')


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

def generate_report(symbol='BTC/USDT'):
    print(f"📊 Генерация отчёта для {symbol}...")

    df = fetch_ohlcv(symbol=symbol)
    df = compute_indicators(df)
    last = df.iloc[-1]
    prev = df.iloc[-2]
    rsi_6h = fetch_rsi_6h(symbol=symbol)

    # Структура рынка по 4h
    df_struct = fetch_ohlcv(symbol=symbol, timeframe='4h')
    df_struct = detect_market_structure(df_struct)
    structure = df_struct.iloc[-1].get('structure', '—')

    text = (
        f"📊 {symbol} (EMA: 30m, RSI: 6h)\n"
        f"Время: {last.name}\n"
        f"Цена:  {last['close']:.2f} USDT\n"
        f"RSI (6h): {rsi_6h:.1f}\n"
        f"EMA20: {last['ema20']:.2f}\n"
        f"EMA50: {last['ema50']:.2f}\n\n"
    )

    # Добавим структуру в текст
    if structure == 'HH-HL':
        text += "📈 Структура (4h): HH–HL — восходящий тренд ⬆️\n"
    elif structure == 'LL-LH':
        text += "📉 Структура (4h): LL–LH — нисходящий тренд ⬇️\n"
    elif structure == 'ChoCH':
        text += "⚠️ Обнаружен ChoCH — возможный разворот тренда 🔄\n"
        logging.info(f"{symbol} — ChoCH обнаружен на 4h")
    elif structure == 'BOS':
        text += "🔁 Обнаружен BOS — тренд подтверждён ✅\n"
        logging.info(f"{symbol} — BOS обнаружен на 4h")

    # Сигналы EMA-кроссовера
    if prev['ema20'] < prev['ema50'] and last['ema20'] > last['ema50']:
        text += "✅ EMA20 пересекла EMA50 снизу вверх — рост вероятен.\n"
    elif prev['ema20'] > prev['ema50'] and last['ema20'] < last['ema50']:
        text += "❌ EMA20 пересекла EMA50 сверху вниз — падение вероятно.\n"

    # Подтверждение тренда по положению цены относительно EMA
    if last['close'] > last['ema20'] and last['close'] > last['ema50']:
        text += "📈 Цена выше EMA20 и EMA50 — восходящий тренд подтверждён.\n"
    elif last['close'] < last['ema20'] and last['close'] < last['ema50']:
        text += "📉 Цена ниже EMA20 и EMA50 — нисходящий тренд подтверждён.\n"
    else:
        text += "⚠️ Цена между EMA20 и EMA50 — тренд неясен.\n"

    # Сигналы RSI (по 6-часовому таймфрейму) + фильтр по EMA
    if rsi_6h < 33:
        text += "🟢 RSI (6h) < 33 — зона перепроданности.\n"
        if last['close'] > last['ema20'] and last['close'] > last['ema50']:
            text += "📥 Сигнал: Вход в сделку на покупку (по RSI + подтверждение EMA).\n"
        else:
            text += "⚠️ RSI < 33, но цена не выше EMA20/EMA50 — сигнал не подтверждён.\n"
    elif rsi_6h > 70:
        text += "🔴 RSI (6h) > 70 — перекупленность.\n"
        if last['close'] < last['ema20'] and last['close'] < last['ema50']:
            text += "📤 Сигнал: Возможен выход из позиции или шорт (по RSI + EMA).\n"
        else:
            text += "⚠️ RSI > 70, но цена не ниже EMA20/EMA50 — сигнал не подтверждён.\n"
    else:
        # Мягкие предупреждения
        if 33 <= rsi_6h <= 36:
            text += "🟡 RSI приближается к зоне перепроданности (33–36).\n"
        elif 65 <= rsi_6h <= 70:
            text += "🟡 RSI приближается к зоне перекупленности (65–70).\n"

        # Проверка близости к EMA
        near_ema20 = last['close'] > last['ema20'] * 0.995
        near_ema50 = last['close'] > last['ema50'] * 0.995
        if near_ema20 and near_ema50:
            text += "🟡 Цена почти выше EMA20 и EMA50 — тренд может подтвердиться.\n"

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
            context.bot.send_message(chat_id=chat_id, text=report)
        except Exception as e:
            context.bot.send_message(chat_id=chat_id, text=f"⚠️ Ошибка при анализе {symbol}: {e}")

def send_filtered_analysis(context: CallbackContext):
    chat_id = context.job.context
    symbols = [
        'BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'DOGE/USDT',
        'LTC/USDT', 'ADA/USDT', 'AVAX/USDT', 'UNI/USDT',
        'LINK/USDT', 'SHIB/USDT', 'ATOM/USDT'
    ]

    sent_count = 0  # ← счётчик отправленных сигналов

    for symbol in symbols:
        try:
            report = generate_report(symbol=symbol)
            if any(x in report for x in ["📥", "📤", "🟡"]):
                context.bot.send_message(chat_id=chat_id, text=report)
                sent_count += 1
            else:
                print(f"[{symbol}] — нет сигнала, отчёт не отправлен.")
        except Exception as e:
            context.bot.send_message(chat_id=chat_id, text=f"⚠️ Ошибка при анализе {symbol}: {e}")

    # 🧾 Финальный итог
    summary = f"📊 Обработано {len(symbols)} пар. Сигналы найдены по {sent_count} из них."
    context.bot.send_message(chat_id=chat_id, text=summary)




def subscribe(update: Update, context: CallbackContext):
    chat_id = update.message.chat_id

    text = (
        "📬 Подписка активна! "
        "🟢 Лонг и 🔴 шорт сигналы будут приходить только по делу — без лишнего шума.\n"
        "🟡 Также получаешь ранние предупреждения, когда рынок приближается к точке входа."
    )
    update.message.reply_text(text)

    # Запускаем проверку каждые 30 минут, но отправляем только если есть сигнал
    context.job_queue.run_repeating(send_filtered_analysis, interval=1800, first=5, context=chat_id)


def unsubscribe(update: Update, context: CallbackContext):
    chat_id = update.message.chat_id
    jobs = context.job_queue.get_jobs_by_name(str(chat_id))
    for job in jobs:
        job.schedule_removal()
    update.message.reply_text("❌ Подписка отменена.")

def main():
    print("🚀 Запуск бота...")  # ← добавлено
    updater = Updater(token=TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("subscribe", subscribe))
    dp.add_handler(CommandHandler("unsubscribe", unsubscribe))

    print("✅ Бот запущен. Ожидаю команды в Telegram...")  # ← добавлено
    keep_alive()
    updater.start_polling()
    updater.idle()


if __name__ == "__main__":
    main()
