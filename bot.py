import os, json, time, threading, websocket, numpy as np
import telebot
from telebot import types

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
DERIV_API_TOKEN = os.getenv("DERIV_API_TOKEN")

bot = telebot.TeleBot(TELEGRAM_TOKEN)
AUTO_RUNNING = True

# ===== DERIV REQUEST =====
def deriv_request(payload):
    ws = websocket.create_connection("wss://ws.derivws.com/websockets/v3?app_id=1089")
    ws.send(json.dumps({"authorize": DERIV_API_TOKEN}))
    ws.recv()
    ws.send(json.dumps(payload))
    result = json.loads(ws.recv())
    ws.close()
    return result

# ===== FETCH CANDLES =====
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

# ===== INDICATORS (NUMPY) =====
def EMA(data, period):
    weights = np.exp(np.linspace(-1., 0., period))
    weights /= weights.sum()
    return np.convolve(data, weights, mode='valid')

def RSI(data, period=14):
    delta = np.diff(data)
    gain = np.where(delta > 0, delta, 0)
    loss = np.where(delta < 0, -delta, 0)
    avg_gain = np.mean(gain[-period:])
    avg_loss = np.mean(loss[-period:])
    rs = avg_gain / avg_loss if avg_loss != 0 else 0
    return 100 - (100 / (1 + rs))

def MACD(data):
    return EMA(data, 12)[-1] - EMA(data, 26)[-1]

def SMA(data, period):
    return np.mean(data[-period:])

# ===== FAST SIGNAL ENGINE =====
def analyze_fast(candles):
    closes = np.array([float(c["close"]) for c in candles])

    rsi = RSI(closes)
    ema9 = EMA(closes, 9)[-1]
    ema21 = EMA(closes, 21)[-1]
    macd = MACD(closes)

    if rsi < 40 and ema9 > ema21 and macd > 0:
        return "BUY", "Fast bullish momentum"

    if rsi > 60 and ema9 < ema21 and macd < 0:
        return "SELL", "Fast bearish momentum"

    return "BUY" if ema9 > ema21 else "SELL", "Momentum prediction"

# ===== SMART AUTO ENGINE =====
def analyze_smart(candles):
    closes = np.array([float(c["close"]) for c in candles])

    rsi = RSI(closes)
    ema9 = EMA(closes, 9)[-1]
    ema21 = EMA(closes, 21)[-1]
    macd = MACD(closes)
    sma50 = SMA(closes, 50)

    buy = 0
    sell = 0

    if rsi < 35: buy += 1
    if ema9 > ema21: buy += 1
    if macd > 0: buy += 1
    if closes[-1] > sma50: buy += 1

    if rsi > 65: sell += 1
    if ema9 < ema21: sell += 1
    if macd < 0: sell += 1
    if closes[-1] < sma50: sell += 1

    if buy >= 3:
        return "BUY", buy
    if sell >= 3:
        return "SELL", sell

    return "WAIT", max(buy, sell)

# ===== MENUS =====
def pairs_menu():
    markup = types.InlineKeyboardMarkup()
    pairs = [
        ("EUR/USD", "frxEURUSD"),
        ("GBP/USD", "frxGBPUSD"),
        ("USD/JPY", "frxUSDJPY")
    ]
    for name, code in pairs:
        markup.add(types.InlineKeyboardButton(name, callback_data=f"pair|{code}"))
    return markup

def timeframe_menu(pair):
    markup = types.InlineKeyboardMarkup()
    for t in [5, 10, 30]:
        markup.add(types.InlineKeyboardButton(f"{t}s", callback_data=f"tf|{pair}|{t}"))
    return markup

def expiration_menu(pair, tf):
    markup = types.InlineKeyboardMarkup()
    for e in ["5s", "15s"]:
        markup.add(types.InlineKeyboardButton(e, callback_data=f"exp|{pair}|{tf}|{e}"))
    return markup

# ===== AUTO LOOP =====
def auto_loop(chat_id):
    pairs = ["frxEURUSD", "frxGBPUSD", "frxUSDJPY"]
    while AUTO_RUNNING:
        for pair in pairs:
            candles = get_candles(pair, 5)
            direction, score = analyze_smart(candles)

            if direction != "WAIT":
                bot.send_message(
                    chat_id,
                    f"🤖 AUTO SIGNAL\n\n"
                    f"Pair: {pair.replace('frx','')}\n"
                    f"TF: 5s | Exp: 5–15s\n"
                    f"Direction: {direction}\n"
                    f"Confirmations: {score}/4\n"
                    f"⚡ Trade Now"
                )
        time.sleep(5)

# ===== START =====
@bot.message_handler(commands=["start"])
def start(message):
    bot.send_message(
        message.chat.id,
        "👑 DERIV AUTO SIGNAL BOT LIVE\n\nChoose Pair:"
    )
    bot.send_message(message.chat.id, "Pairs:", reply_markup=pairs_menu())

    threading.Thread(target=auto_loop, args=(message.chat.id,), daemon=True).start()

# ===== CALLBACK =====
@bot.callback_query_handler(func=lambda call: True)
def callback(call):
    data = call.data.split("|")

    if data[0] == "pair":
        bot.send_message(call.message.chat.id, "Select Timeframe:", reply_markup=timeframe_menu(data[1]))

    elif data[0] == "tf":
        bot.send_message(call.message.chat.id, "Select Expiration:", reply_markup=expiration_menu(data[1], data[2]))

    elif data[0] == "exp":
        pair = data[1]
        tf = int(data[2])
        exp = data[3]

        candles = get_candles(pair, tf)
        direction, reason = analyze_fast(candles)

        bot.send_message(
            call.message.chat.id,
            f"📊 MANUAL SIGNAL\n\n"
            f"Pair: {pair.replace('frx','')}\n"
            f"TF: {tf}s | Exp: {exp}\n"
            f"Direction: {direction}\n"
            f"Reason: {reason}\n"
            f"⚡ Enter Now"
        )

print("🚀 BOT LIVE")
bot.polling()