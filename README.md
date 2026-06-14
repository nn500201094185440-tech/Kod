# 🚀 Telegram Crypto Pump Scanner Bot

يراقب أسواق Spot وFutures على Bybit وMEXC ويرسل تنبيهات Telegram عند اكتشاف علامات Pump محتملة.

---

## 📦 هيكل الملفات

```
pump_scanner/
├── main.py              ← نقطة البداية (شغّل هذا الملف)
├── scanner.py           ← محرك المسح الرئيسي
├── analyzer.py          ← نظام تقييم الإشارات (0-100)
├── database.py          ← قاعدة بيانات SQLite
├── telegram_bot.py      ← إرسال التنبيهات
├── config.yaml          ← ⭐ إعداداتك (عدّل هذا الملف)
├── requirements.txt     ← المكتبات المطلوبة
├── exchanges/
│   ├── bybit.py         ← واجهة Bybit API
│   └── mexc.py          ← واجهة MEXC API
├── data/                ← قاعدة البيانات (تُنشأ تلقائياً)
└── logs/                ← ملفات السجل (تُنشأ تلقائياً)
```

---

## ⚙️ الإعداد (خطوة بخطوة)

### 1. تثبيت Python

تأكد أن Python 3.9+ مثبت:
```bash
python --version
```

### 2. تثبيت المكتبات

```bash
pip install -r requirements.txt
```

### 3. إنشاء بوت Telegram

1. افتح Telegram وابحث عن **@BotFather**
2. أرسل `/newbot` واتبع التعليمات
3. انسخ **Bot Token** الذي ستحصل عليه

### 4. الحصول على Chat ID

- أرسل رسالة لبوت **@userinfobot** في Telegram
- ستحصل على `chat_id` الخاص بك

أو إذا كنت تريد إرسال لقناة:
- أضف البوت كمشرف في القناة
- `chat_id` القناة يكون بالشكل: `@channel_username` أو `-100XXXXXXXXXX`

### 5. تعديل config.yaml

```yaml
telegram:
  bot_token: "1234567890:ABCdef..."   # ← ضع token البوت هنا
  chat_id: "123456789"                # ← ضع chat_id هنا
```

### 6. تشغيل البوت

```bash
python main.py
```

---

## 📊 شرح نظام التقييم (Signal Score)

| المعيار | الوزن | التفاصيل |
|---------|-------|----------|
| Price Momentum | 20% | ارتفاع 5m/15m/1h |
| Volume Spike | 30% | حجم التداول × المتوسط |
| Buy Pressure | 20% | نسبة أوامر الشراء |
| Breakout | 20% | كسر أعلى سعر سابق |
| Liquidity | 10% | السبريد وعمق الأوردر بوك |

**التنبيه يُرسل فقط إذا Score ≥ 75/100**

---

## 📱 مثال على رسالة التنبيه

```
🚀 Possible Pump Alert!
━━━━━━━━━━━━━━━━━━━━━
🔵 MEXC  📈 SPOT

🪙 Coin: XYZ/USDT
💰 Price: $0.01250

📉 Price Change:
  ├ 5m:  +2.8%
  ├ 15m: +5.4%
  └ 1h:  +8.2%

📦 Volume Spike: +420%
💚 Buy Pressure: 68%
💧 24h Volume: $12M
🔔 Breakout: Broke 15M High

📊 Signal Score: 84/100
🟠 [████████░░] 84/100

💡 5m +2.8% • Vol x5.2 • Buy 68% • Broke 15m high
━━━━━━━━━━━━━━━━━━━━━
⚠️ Not financial advice. DYOR.
```

---

## ⚙️ تخصيص الإعدادات

### تغيير حساسية البوت (في config.yaml)

```yaml
# تخفيف الشروط (تنبيهات أكثر)
price_momentum:
  min_change_5m: 1.5      # كان 2.0
  min_change_15m: 2.0     # كان 3.0

scoring:
  min_score_to_alert: 65  # كان 75
```

```yaml
# تشديد الشروط (تنبيهات أدق)
price_momentum:
  min_change_5m: 3.0
  min_change_15m: 5.0

scoring:
  min_score_to_alert: 85
volume:
  spike_multiplier: 5.0   # كان 3.0
```

### تغيير فترة إعادة التنبيه

```yaml
telegram:
  alert_cooldown_minutes: 60  # لا تكرر التنبيه لنفس العملة قبل ساعة
```

---

## 🖥️ التشغيل في الخلفية (Linux/VPS)

### باستخدام screen

```bash
screen -S pump_scanner
python main.py
# اضغط Ctrl+A ثم D للخروج مع إبقاء البوت يعمل
```

### باستخدام systemd

أنشئ ملف `/etc/systemd/system/pump_scanner.service`:
```ini
[Unit]
Description=Crypto Pump Scanner Bot
After=network.target

[Service]
User=your_username
WorkingDirectory=/path/to/pump_scanner
ExecStart=/usr/bin/python3 main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

ثم:
```bash
sudo systemctl enable pump_scanner
sudo systemctl start pump_scanner
sudo systemctl status pump_scanner
```

---

## ❗ ملاحظات مهمة

- **هذا ليس بوت تداول تلقائي** - فقط مراقبة وإشعارات
- لا يتطلب API keys (يستخدم APIs العامة فقط)
- يُنصح بتشغيله على VPS لضمان الاستمرارية
- Pump signals ليست ضماناً للربح - دائماً DYOR
