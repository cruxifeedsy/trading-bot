import os
import json
import time
import threading
import websocket
import telebot
import pandas as pd
from telebot import types

from ta.momentum import RSIIndicator, StochasticOscillator
from ta.trend import EMAIndicator, MACD, SMAIndicator
from ta.volatility import BollingerBands

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

# ===== FAST MANUAL ENGINE (3–4 INDICATORS) =====

def analyze_market_fast(candles):
    closes = [float(c["close"]) for c in candles]
    df = pd.DataFrame({"close": closes})

    df["rsi"] = RSIIndicator(df["close"], 14).rsi()
    df["ema9"] = EMAIndicator(df["close"], 9).ema_indicator()
    df["ema21"] = EMAIndicator(df["close"], 21).ema_indicator()
    df["macd"] = MACD(df["close"]).macd_diff()

    latest = df.iloc[-1]

    if latest["rsi"] < 40 and latest["ema9"] > latest["ema21"] and latest["macd"] > 0:
        return "BUY", "Fast bullish momentum"

    if latest["rsi"] > 60 and latest["ema9"] < latest["ema21"] and latest["macd"] < 0:
        return "SELL", "Fast bearish momentum"

    return "BUY" if latest["ema9"] > latest["ema21"] else "SELL", "Momentum prediction"

# ===== SMART AUTO ENGINE (8+ INDICATORS) =====

def analyze_market_smart(candles):
    closes = [float(c["close"]) for c in candles]
    highs = [float(c["high"]) for c in candles]
    lows = [float(c["low"]) for c in candles]

    df = pd.DataFrame({
        "close": closes,
        "high": highs,
        "low": lows
    })

    df["rsi"] = RSIIndicator(df["close"], 14).rsi()
    df["ema9"] = EMAIndicator(df["close"], 9).ema_indicator()
    df["ema21"] = EMAIndicator(df["close"], 21).ema_indicator()
    df["sma50"] = SMAIndicator(df["close"], 50).sma_indicator()
    df["macd"] = MACD(df["close"]).macd_diff()
    df["stoch"] = StochasticOscillator(df["high"], df["low"], df["close"]).stoch()
    bb = BollingerBands(df["close"])
    df["bb_high"] = bb.bollinger_hband()
    df["bb_low"] = bb.bollinger_lband()

    latest = df.iloc[-1]

    buy = 0
    sell = 0

    # BUY confirmations
    if latest["rsi"] < 35: buy += 1
    if latest["ema9"] > latest["ema21"]: buy += 1
    if latest["macd"] > 0: buy += 1
    if latest["stoch"] < 30: buy += 1
    if latest["close"] < latest["bb_low"]: buy += 1
    if latest["close"] > latest["sma50"]: buy += 1

    # SELL confirmations
    if latest["rsi"] > 65: sell += 1
    if latest["ema9"] < latest["ema21"]: sell += 1
    if latest["macd"] < 0: sell += 1
    if latest["stoch"] > 70: sell += 1
    if latest["close"] > latest["bb_high"]: sell += 1
    if latest["close"] < latest["sma50"]: sell += 1

    if buy >= 6:
        return "BUY", buy

    if sell >= 6:
        return "SELL", sell

    return "WAIT", max(buy, sell)

# ===== PAIRS MENU =====

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

# ===== TIMEFRAME MENU =====

def timeframe_menu(pair):
    markup = types.InlineKeyboardMarkup(row_width=3)
    tfs = [("5s", 5), ("10s", 10), ("30s", 30)]
    for name, sec in tfs:
        markup.add(types.InlineKeyboardButton(name, callback_data=f"tf|{pair}|{sec}"))
    return markup

# ===== EXPIRATION MENU =====

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

# ===== START COMMAND =====

@bot.message_handler(commands=["start"])
def start(message):
    bot.send_message(message.chat.id, "👑 CRUXIFEED GOD-LEVEL SIGNAL BOT\n\nAuto trading is ACTIVE.\nManual mode available below.")
    bot.send_message(message.chat.id, "📌 Select Pair:", reply_markup=pairs_menu())

    threading.Thread(target=auto_trade_loop, args=(message.chat.id,), daemon=True).start()

# ===== CALLBACK HANDLER =====

@bot.callback_query_handler(func=lambda call: True)
def handle_query(call):
    data = call.data.split("|")

    # PAIR
    if data[0] == "pair":
        pair = data[1]
        bot.send_message(call.message.chat.id, "⏱ Choose Timeframe:", reply_markup=timeframe_menu(pair))

    # TIMEFRAME
    elif data[0] == "tf":
        pair, tf = data[1], data[2]
        bot.send_message(call.message.chat.id, "⌛ Choose Expiration:", reply_markup=expiration_menu(pair, tf))

    # EXPIRATION
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
            "⚡ Execute immediately"
        )
        bot.send_message(call.message.chat.id, signal, parse_mode="Markdown")

# ===== RUN BOT =====

print("🚀 CRUXIFEED ELITE BOT RUNNING...")
bot.polling()