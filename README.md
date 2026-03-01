# هيلين WiFi - Helen WiFi

سيرفر اتصالات داخلي بحت: مكالمات صوت/فيديو + دردشة + ملفات + Mesh + دعم فايبر.
لا يعتمد على أي خدمة خارجية - يعمل بالكامل على الشبكة المحلية بدون إنترنت.

## المميزات

- مكالمات صوتية وفيديو (WebRTC - شبكة محلية)
- دردشة فورية (عامة + خاصة)
- مشاركة ملفات مع شريط تقدم
- شبكة Mesh بين السيرفرات
- لوحة تحكم كاملة
- يدعم كل الراوترات (WiFi/Ethernet/DSL/Fiber/GPON/EPON/SFP/ONT/ONU)
- بناء EXE بضغطة واحدة
- اتصال داخلي بحت - بدون اعتماد على خدمات خارجية

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
