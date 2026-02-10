import os
import json
import time
import threading
import websocket
import telebot
import pandas as pd
from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator, MACD
from telebot import types

# ===== ENV VARIABLES =====
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
DERIV_API_TOKEN = os.getenv("DERIV_API_TOKEN")

bot = telebot.TeleBot(TELEGRAM_TOKEN)

AUTO_SIGNAL = False
PRICE_CACHE = {}

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

def get_candles(symbol, granularity=60, count=50):
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

# ===== SIGNAL ENGINE =====

def analyze_market(candles):
    closes = [float(c["close"]) for c in candles]
    df = pd.DataFrame({"close": closes})

    df["rsi"] = RSIIndicator(df["close"], 14).rsi()
    df["ema9"] = EMAIndicator(df["close"], 9).ema_indicator()
    df["ema21"] = EMAIndicator(df["close"], 21).ema_indicator()
    macd = MACD(df["close"])
    df["macd"] = macd.macd_diff()

    latest = df.iloc[-1]

    # BUY RULE
    if latest["rsi"] < 35 and latest["ema9"] > latest["ema21"] and latest["macd"] > 0:
        return "BUY", "Bullish reversal confirmed"

    # SELL RULE
    if latest["rsi"] > 65 and latest["ema9"] < latest["ema21"] and latest["macd"] < 0:
        return "SELL", "Bearish reversal confirmed"

    return "NO TRADE", "Market unclear — skipping risky trade"

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
    markup = types.InlineKeyboardMarkup(row_width=2)
    tfs = [("M1", 60), ("M5", 300), ("M15", 900)]
    for name, seconds in tfs:
        markup.add(types.InlineKeyboardButton(name, callback_data=f"tf|{pair}|{seconds}"))
    return markup

def expiration_menu(pair, tf):
    markup = types.InlineKeyboardMarkup(row_width=2)
    exps = ["30s", "1m", "3m", "5m"]
    for e in exps:
        markup.add(types.InlineKeyboardButton(e, callback_data=f"exp|{pair}|{tf}|{e}"))
    return markup

# ===== AUTO SIGNAL LOOP =====

def auto_signal_loop(chat_id):
    global AUTO_SIGNAL
    pairs = ["frxEURUSD", "frxGBPUSD", "frxUSDJPY"]

    while AUTO_SIGNAL:
        for pair in pairs:
            candles = get_candles(pair, 300)
            direction, reason = analyze_market(candles)

            if direction != "NO TRADE":
                msg = (
                    f"🤖 AUTO SIGNAL\n\n"
                    f"💱 Pair: {pair.replace('frx','')}\n"
                    f"📊 TF: M5\n"
                    f"📉 Direction: {direction}\n"
                    f"⏱ Exp: 1m\n\n"
                    f"🧠 Reason: {reason}\n"
                    f"⚠️ Trade responsibly"
                )
                bot.send_message(chat_id, msg)

        time.sleep(300)

# ===== START COMMAND =====

@bot.message_handler(commands=["start"])
def start(message):
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("📈 Trade Now", callback_data="trade_now"),
        types.InlineKeyboardButton("🤖 Auto Signals", callback_data="auto_trade")
    )
    bot.send_message(message.chat.id, "🚀 CRUXIFEED DERIV SIGNAL BOT", reply_markup=markup)

# ===== CALLBACK HANDLER =====

@bot.callback_query_handler(func=lambda call: True)
def handle_query(call):
    global AUTO_SIGNAL
    data = call.data.split("|")

    if data[0] == "trade_now":
        bot.edit_message_text("Select Pair:", call.message.chat.id, call.message.message_id, reply_markup=pairs_menu())

    elif data[0] == "pair":
        pair = data[1]
        bot.edit_message_text(f"Pair Selected\nChoose Timeframe:", call.message.chat.id, call.message.message_id, reply_markup=timeframe_menu(pair))

    elif data[0] == "tf":
        pair, tf = data[1], data[2]
        bot.edit_message_text(f"Choose Expiration:", call.message.chat.id, call.message.message_id, reply_markup=expiration_menu(pair, tf))

    elif data[0] == "exp":
        pair, tf, exp = data[1], int(data[2]), data[3]
        bot.send_message(call.message.chat.id, "🔍 Analyzing market...")

        candles = get_candles(pair, tf)
        direction, reason = analyze_market(candles)

        if direction == "NO TRADE":
            bot.send_message(call.message.chat.id, "⚠️ No safe trade found — wait.")
            return

        signal = (
            f"👑 CRUXIFEED SIGNAL 👑\n\n"
            f"💱 Pair: {pair.replace('frx','')}\n"
            f"📊 Timeframe: {tf//60}m\n"
            f"⏱ Expiration: {exp}\n"
            f"📉 Direction: {direction}\n\n"
            f"🧠 Reason: {reason}\n"
            f"⚠️ Manage risk wisely"
        )
        bot.send_message(call.message.chat.id, signal)

    elif data[0] == "auto_trade":
        AUTO_SIGNAL = True
        bot.send_message(call.message.chat.id, "🤖 Auto Signals Enabled")
        threading.Thread(target=auto_signal_loop, args=(call.message.chat.id,)).start()

# ===== RUN BOT =====
bot.polling()