# هيلين WiFi - Helen WiFi

سيرفر اتصالات بسيط: مكالمات صوت/فيديو + دردشة + ملفات + Mesh + دعم فايبر.

## المميزات

- مكالمات صوتية وفيديو (WebRTC + TURN)
- دردشة فورية (عامة + خاصة)
- مشاركة ملفات مع شريط تقدم
- شبكة Mesh بين السيرفرات
- لوحة تحكم كاملة
- يدعم كل الراوترات (WiFi/Ethernet/DSL/Fiber/GPON/EPON/SFP/ONT/ONU)
- بناء EXE بضغطة واحدة

## التشغيل

```bash
pip install -r requirements.txt
python run.py --verbose
```

- العميل: http://localhost:8400/client
- الادمن: http://localhost:8400/admin (admin / admin123)

## بناء EXE

```bash
python build.py
```
