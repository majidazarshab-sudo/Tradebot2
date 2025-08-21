
from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.button import Button
import threading, json, re, time, hmac, hashlib, requests, os, math
from urllib.parse import urlencode
from telethon import TelegramClient, events

CONFIG_FILE = "config.json"
LOG_FILE = "tradelog.json"

# ---------------- UI ----------------
class ConfigScreen(BoxLayout):
    def __init__(self, start_callback, **kwargs):
        super().__init__(**kwargs)
        self.orientation = "vertical"

        # Telegram & LBank creds
        self.api_id_input = TextInput(hint_text="Telegram API ID", multiline=False)
        self.api_hash_input = TextInput(hint_text="Telegram API Hash", multiline=False)
        self.channel_input = TextInput(hint_text="Telegram Channel Username (e.g. @signals)", multiline=False)
        self.lbank_key_input = TextInput(hint_text="LBank API Key", multiline=False)
        self.lbank_secret_input = TextInput(hint_text="LBank API Secret", multiline=False, password=True)

        # TP splits (%), default 40/40/20
        self.tp1_split = TextInput(text="40", hint_text="TP1 %", multiline=False)
        self.tp2_split = TextInput(text="40", hint_text="TP2 %", multiline=False)
        self.tp3_split = TextInput(text="20", hint_text="TP3 %", multiline=False)

        self.add_widget(self.api_id_input)
        self.add_widget(self.api_hash_input)
        self.add_widget(self.channel_input)
        self.add_widget(self.lbank_key_input)
        self.add_widget(self.lbank_secret_input)
        self.add_widget(Label(text="TP splits % (default 40/40/20):"))
        self.add_widget(self.tp1_split)
        self.add_widget(self.tp2_split)
        self.add_widget(self.tp3_split)

        self.start_btn = Button(text="Start Bot")
        self.start_btn.bind(on_press=lambda x: start_callback(
            self.api_id_input.text,
            self.api_hash_input.text,
            self.channel_input.text,
            self.lbank_key_input.text,
            self.lbank_secret_input.text,
            self.get_splits()
        ))
        self.add_widget(self.start_btn)

    def get_splits(self):
        def to_num(s):
            try:
                return float(s.strip())
            except:
                return 0.0
        s1, s2, s3 = to_num(self.tp1_split.text), to_num(self.tp2_split.text), to_num(self.tp3_split.text)
        total = s1 + s2 + s3
        if total <= 0:
            return [0.4, 0.4, 0.2]
        return [s1/total, s2/total, s3/total]

class TradeBot(BoxLayout):
    def __init__(self, api_key, api_secret, tp_splits, **kwargs):
        super().__init__(**kwargs)
        self.orientation = "vertical"
        self.log = Label(text="ربات آماده است...", halign="left", valign="top")
        self.add_widget(self.log)

        self.tp_splits = tp_splits  # proportions list like [0.4,0.4,0.2]

        self.history_btn = Button(text="📜 نمایش تاریخچه معاملات")
        self.history_btn.bind(on_press=lambda x: self.show_history())
        self.add_widget(self.history_btn)

        threading.Thread(target=self.update_positions, args=(api_key, api_secret), daemon=True).start()

    def add_log(self, msg):
        self.log.text += f"\n{msg}"

    def update_positions(self, api_key, api_secret):
        while True:
            try:
                positions = get_open_positions(api_key, api_secret)
                self.log.text += f"\n📊 پوزیشن‌های باز: {positions}"
            except Exception as e:
                self.log.text += f"\n❌ خطا در دریافت پوزیشن‌ها: {e}"
            time.sleep(20)

    def show_history(self):
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                logs = f.read()
            self.log.text += f"\n===== تاریخچه معاملات =====\n{logs}"
        else:
            self.log.text += "\n📭 هیچ تاریخچه‌ای وجود ندارد."

# ---------------- Utils/Logs ----------------
def save_log(entry):
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

def sign_payload(payload, secret):
    query = urlencode(payload)
    signature = hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()
    return signature

def lbank_request(endpoint, payload, api_key, api_secret):
    payload["api_key"] = api_key
    payload["timestamp"] = int(time.time() * 1000)
    payload["sign"] = sign_payload(payload, api_secret)
    url = f"https://api.lbkex.com{endpoint}"
    r = requests.post(url, data=payload, timeout=20)
    return r.json()

def get_available_usdt(api_key, api_secret):
    # NOTE: endpoint name may differ; adjust to LBank docs if needed
    try:
        res = lbank_request("/v2/futures/balance", {}, api_key, api_secret)
        # Expecting something like: {"assets":[{"asset":"USDT","available":"123.45",...}], ...}
        if isinstance(res, dict):
            assets = res.get("assets") or res.get("data") or []
            for a in assets:
                sym = (a.get("asset") or a.get("currency") or "").upper()
                if sym in ("USDT","USD"):
                    avail = a.get("available") or a.get("availableBalance") or a.get("free")
                    if avail is not None:
                        return float(avail)
    except Exception as e:
        pass
    return 0.0

def normalize_symbol(raw):
    # Accept styles: "SOL/USDT", "SOL-USDT", "sol_usdt", "Symbol: SOLUSDT"
    m = re.search(r'([A-Za-z]{2,10})\s*[/\-_ ]?\s*(USDT|USD|USDC)\b', raw, re.I)
    if not m:
        m = re.search(r'symbol\s*[:=]\s*([A-Za-z0-9/_\-]+)', raw, re.I)
        if m:
            raw_pair = m.group(1)
            raw = raw_pair
            m = re.search(r'([A-Za-z]{2,10})\s*[/\-_ ]?\s*(USDT|USD|USDC)\b', raw, re.I)
    if m:
        base = m.group(1).lower()
        quote = m.group(2).lower()
        return f"{base}_{quote}"
    # Fallback to sol_usdt
    return "sol_usdt"

def parse_leverage(text, default_lev=12):
    # Matches: "leverage: 12", "lev 15x", "x20", "20x", "leverage=25x"
    patterns = [
        r'leverage\s*[:=]?\s*(\d+)\s*x?',
        r'lev\s*[:=]?\s*(\d+)\s*x?',
        r'(\d+)\s*x\b',
        r'\bx\s*(\d+)\b'
    ]
    for p in patterns:
        m = re.search(p, text, re.I)
        if m:
            try:
                v = int(m.group(1))
                if 1 <= v <= 125:
                    return v
            except: pass
    return default_lev

def place_futures_order(symbol, side, size_base, leverage, entry, sl, tps, tp_splits, api_key, api_secret):
    # Open market position
    payload = {
        "symbol": symbol,
        "type": "market",
        "side": side,              # 'buy' for LONG, 'sell' for SHORT
        "size": size_base,
        "open_type": "isolated",
        "leverage": leverage,
        "position_id": 0,
    }
    res = lbank_request("/v2/futures/order", payload, api_key, api_secret)

    log_entry = {"symbol": symbol, "side": side, "entry": entry, "sl": sl, "tps": tps, "size": size_base, "lev": leverage, "result": res}
    save_log(log_entry)

    if res.get("result", True):
        # Distribute size by tp_splits among available TPs
        valid_tps = [tp for tp in tps if tp]
        if valid_tps:
            # Normalize splits to number of TPs
            splits = tp_splits[:len(valid_tps)]
            # Re-normalize to sum=1 for the count used
            ssum = sum(splits) if sum(splits) > 0 else 1.0
            splits = [s/ssum for s in splits]
            for tp, frac in zip(valid_tps, splits):
                tp_size = max(0.0, size_base * frac)
                tp_payload = {
                    "symbol": symbol,
                    "side": "sell" if side == "buy" else "buy",
                    "size": tp_size,
                    "type": "take_profit",
                    "stop_price": tp,
                    "leverage": leverage,
                    "open_type": "isolated"
                }
                lbank_request("/v2/futures/order", tp_payload, api_key, api_secret)

        if sl:
            sl_payload = {
                "symbol": symbol,
                "side": "sell" if side == "buy" else "buy",
                "size": size_base,
                "type": "stop",
                "stop_price": sl,
                "leverage": leverage,
                "open_type": "isolated"
            }
            lbank_request("/v2/futures/order", sl_payload, api_key, api_secret)
    return res

def get_open_positions(api_key, api_secret):
    return lbank_request("/v2/futures/positions", {}, api_key, api_secret)

# ---------------- Telegram loop ----------------
def run_telegram(bot_ui, api_id, api_hash, channel, api_key, api_secret, tp_splits):
    client = TelegramClient("session", int(api_id), api_hash)

    @client.on(events.NewMessage(chats=channel))
    async def handler(event):
        text = event.message.message
        bot_ui.add_log("سیگنال جدید: " + text)

        up = text.upper()
        side = "buy" if "LONG" in up else "sell"

        # Parse symbol and leverage from the message
        symbol = normalize_symbol(text)  # default sol_usdt if not found
        lev = parse_leverage(text, default_lev=12)

        # Prices
        entry = re.findall(r"Enter price\s*[:：]\s*([\d\.]+)", text, re.I)
        tp1 = re.findall(r"TP1\s*[:：]\s*([\d\.]+)", text, re.I)
        tp2 = re.findall(r"TP2\s*[:：]\s*([\d\.]+)", text, re.I)
        tp3 = re.findall(r"TP3\s*[:：]\s*([\d\.]+)", text, re.I)
        sl = re.findall(r"Stop Loss\s*[:：]\s*([\d\.]+)", text, re.I)

        if entry and sl and (tp1 or tp2 or tp3):
            entry = float(entry[0])
            tps = []
            if tp1: tps.append(float(tp1[0]))
            if tp2: tps.append(float(tp2[0]))
            if tp3: tps.append(float(tp3[0]))
            sl = float(sl[0])

            # Compute size = 30% of available USDT * leverage / entry (base units)
            avail = get_available_usdt(api_key, api_secret)
            notional = max(0.0, 0.30 * avail * lev)  # 30% balance with leverage
            size_base = 0.0
            if entry > 0:
                size_base = round(notional / entry, 6)  # 6 decimals default

            bot_ui.add_log(f"🔧 symbol={symbol}, lev={lev}, availUSDT={avail}, size={size_base}")
            res = place_futures_order(symbol, side, size_base, lev, entry, sl, tps, tp_splits, api_key, api_secret)
            bot_ui.add_log(f"سفارش ارسال شد: {res}")
        else:
            bot_ui.add_log("⚠️ قالب پیام با الگو هم‌خوانی ندارد.")

    client.start()
    client.run_until_disconnected()

# ---------------- App ----------------
class TradeApp(App):
    def build(self):
        return ConfigScreen(self.start_bot)

    def start_bot(self, api_id, api_hash, channel, lbank_key, lbank_secret, tp_splits):
        with open(CONFIG_FILE, "w") as f:
            json.dump({
                "api_id": api_id,
                "api_hash": api_hash,
                "channel": channel,
                "lbank_key": lbank_key,
                "lbank_secret": lbank_secret,
                "tp_splits": tp_splits
            }, f)

        self.root.clear_widgets()
        ui = TradeBot(lbank_key, lbank_secret, tp_splits)
        self.root.add_widget(ui)

        threading.Thread(target=run_telegram, args=(ui, api_id, api_hash, channel, lbank_key, lbank_secret, tp_splits), daemon=True).start()

if __name__ == "__main__":
    TradeApp().run()
