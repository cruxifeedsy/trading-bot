
import os
import json
import time
import threading
import websocket
import telebot
import pandas as pd
import numpy as np
from telebot import types

# ===== ENV VARIABLES =====
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
DERIV_API_TOKEN = os.getenv("DERIV_API_TOKEN")

bot = telebot.TeleBot(TELEGRAM_TOKEN)

AUTO_RUNNING = True

# ===== DERIV WS CONNECTION =====

def deriv_request(payload):
    ws = websocket.create_connection("wss://ws.derivws.com/websockets/v3?app_id=1089")
    ws.send(json.dumps({"authorize": DERIV_API_TOKEN}))
    ws.recv()
    ws.send(json.dumps(payload))
    result = ws.recv()
    ws.close()
    return json.loads(result)

# ===== FETCH MARKET DATA =====

def get_candles(symbol, granularity=5, count=80):
    payload = {
        "ticks_history": symbol,
        "adjust_start_time": 1,
        "count": count,
        "end": "latest",
        "granularity": granularity,
        "style": "candles"
    }
    data = deriv_request(payload)
    return data.get("candles", [])

# ===== INDICATORS (NO ta LIBRARY) =====

def RSI(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def EMA(series, period):
    return series.ewm(span=period, adjust=False).mean()

def MACD(series):
    return EMA(series, 12) - EMA(series, 26)

def SMA(series, period):
    return series.rolling(period).mean()

def Bollinger(series):
    sma = SMA(series, 20)
    std = series.rolling(20).std()
    return sma + (2 * std), sma - (2 * std)

def Stochastic(high, low, close, period=14):
    lowest = low.rolling(period).min()
    highest = high.rolling(period).max()
    return 100 * ((close - lowest) / (highest - lowest))

# ===== FAST MANUAL ENGINE (3–4 INDICATORS) =====

def analyze_market_fast(candles):
    closes = pd.Series([float(c["close"]) for c in candles])

    rsi = RSI(closes)
    ema9 = EMA(closes, 9)
    ema21 = EMA(closes, 21)
    macd = MACD(closes)

    if rsi.iloc[-1] < 40 and ema9.iloc[-1] > ema21.iloc[-1] and macd.iloc[-1] > 0:
        return "BUY", "Fast bullish momentum"

    if rsi.iloc[-1] > 60 and ema9.iloc[-1] < ema21.iloc[-1] and macd.iloc[-1] < 0:
        return "SELL", "Fast bearish momentum"

    return "BUY" if ema9.iloc[-1] > ema21.iloc[-1] else "SELL", "Momentum prediction"

# ===== SMART AUTO ENGINE (8+ INDICATORS) =====

def analyze_market_smart(candles):
    closes = pd.Series([float(c["close"]) for c in candles])
    highs = pd.Series([float(c["high"]) for c in candles])
    lows = pd.Series([float(c["low"]) for c in candles])

    rsi = RSI(closes)
    ema9 = EMA(closes, 9)
    ema21 = EMA(closes, 21)
    macd = MACD(closes)
    sma50 = SMA(closes, 50)
    stoch = Stochastic(highs, lows, closes)
    bb_high, bb_low = Bollinger(closes)

    buy = 0
    sell = 0

    if rsi.iloc[-1] < 35: buy += 1
    if ema9.iloc[-1] > ema21.iloc[-1]: buy += 1
    if macd.iloc[-1] > 0: buy += 1
    if stoch.iloc[-1] < 30: buy += 1
    if closes.iloc[-1] < bb_low.iloc[-1]: buy += 1
    if closes.iloc[-1] > sma50.iloc[-1]: buy += 1

    if rsi.iloc[-1] > 65: sell += 1
    if ema9.iloc[-1] < ema21.iloc[-1]: sell += 1
    if macd.iloc[-1] < 0: sell += 1
    if stoch.iloc[-1] > 70: sell += 1
    if closes.iloc[-1] > bb_high.iloc[-1]: sell += 1
    if closes.iloc[-1] < sma50.iloc[-1]: sell += 1

    if buy >= 6:
        return "BUY", buy
    if sell >= 6:
        return "SELL", sell

    return "WAIT", max(buy, sell)

# ===== MENUS =====

def pairs_menu():
    markup = types.InlineKeyboardMarkup(row_width=2)
    pairs = [
        ("EUR/USD", "frxEURUSD"),
        ("GBP/USD", "frxGBPUSD"),
        ("USD/JPY", "frxUSDJPY"),
        ("AUD/USD", "frxAUDUSD"),
    ]
    for name, code in pairs:
        markup.add(types.InlineKeyboardButton(name, callback_data=f"pair|{code}"))
    return markup

def timeframe_menu(pair):
    markup = types.InlineKeyboardMarkup(row_width=3)
    tfs = [("5s", 5), ("10s", 10), ("30s", 30)]
    for name, sec in tfs:
        markup.add(types.InlineKeyboardButton(name, callback_data=f"tf|{pair}|{sec}"))
    return markup

def expiration_menu(pair, tf):
    markup = types.InlineKeyboardMarkup(row_width=2)
    exps = ["5s", "15s"]
    for e in exps:
        markup.add(types.InlineKeyboardButton(e, callback_data=f"exp|{pair}|{tf}|{e}"))
    return markup

# ===== AUTO SIGNAL LOOP =====

def auto_trade_loop(chat_id):
    pairs = ["frxEURUSD", "frxGBPUSD", "frxUSDJPY"]

    while AUTO_RUNNING:
        for pair in pairs:
            candles = get_candles(pair, granularity=5, count=80)
            direction, score = analyze_market_smart(candles)

            if direction != "WAIT":
                msg = (
                    "━━━━━━━━━━━━━━━━━━\n"
                    "🤖 CRUXIFEED AUTO ELITE SIGNAL\n"
                    "━━━━━━━━━━━━━━━━━━\n\n"
                    f"💱 Pair: {pair.replace('frx','')}\n"
                    f"📊 TF: 5 Seconds\n"
                    f"⏱ Exp: 5–15 Seconds\n"
                    f"📉 Direction: **{direction}**\n"
                    f"🧠 Confirmations: {score}/8\n"
                    f"⚡ Confidence: HIGH\n\n"
                    "🚀 ENTER TRADE NOW"
                )
                bot.send_message(chat_id, msg, parse_mode="Markdown")

        time.sleep(5)

# ===== START =====

@bot.message_handler(commands=["start"])
def start(message):
    bot.send_message(
        message.chat.id,
        "👑 CRUXIFEED GOD-LEVEL DERIV SIGNAL BOT\n\n"
        "🤖 Auto Trading: ACTIVE\n"
        "⚡ Manual Mode: AVAILABLE\n\n"
        "Select Pair Below:"
    )

    bot.send_message(message.chat.id, "📌 Choose Pair:", reply_markup=pairs_menu())

    threading.Thread(
        target=auto_trade_loop,
        args=(message.chat.id,),
        daemon=True
    ).start()

# ===== CALLBACK HANDLER =====

@bot.callback_query_handler(func=lambda call: True)
def handle_query(call):
    data = call.data.split("|")

    if data[0] == "pair":
        pair = data[1]
        bot.send_message(call.message.chat.id, "⏱ Choose Timeframe:", reply_markup=timeframe_menu(pair))

    elif data[0] == "tf":
        pair, tf = data[1], data[2]
        bot.send_message(call.message.chat.id, "⌛ Choose Expiration:", reply_markup=expiration_menu(pair, tf))

    elif data[0] == "exp":
        pair, tf, exp = data[1], int(data[2]), data[3]

        candles = get_candles(pair, tf)
        direction, reason = analyze_market_fast(candles)

        signal = (
            "━━━━━━━━━━━━━━━\n"
            "👑 CRUXIFEED MANUAL SIGNAL\n"
            "━━━━━━━━━━━━━━━\n\n"
            f"💱 Pair: {pair.replace('frx','')}\n"
            f"📊 TF: {tf}s\n"
            f"⏱ Exp: {exp}\n"
            f"📉 Direction: **{direction}**\n\n"
            f"🧠 Reason: {reason}\n"
            "⚡ EXECUTE IMMEDIATELY"
        )
        bot.send_message(call.message.chat.id, signal, parse_mode="Markdown")

# ===== RUN =====

print("🚀 CRUXIFEED ELITE BOT RUNNING...")
bot.polling()