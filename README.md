# هيلين WiFi - Helen WiFi

سيرفر اتصالات كامل عبر WiFi مع مكالمات صوت/فيديو، محادثات فورية، مشاركة ملفات، شبكة Mesh، ولوحة تحكم كاملة.

## المميزات

- مكالمات صوتية وفيديو (WebRTC) بأقصى دقة للكاميرا
- محادثات فورية (عامة + خاصة)
- مشاركة ملفات بحجم غير محدود مع شريط تقدم
- شبكة Mesh - حتى 100+ سيرفر يتصلون ببعض
- لوحة تحكم كاملة مع مراقبة مباشرة
- كشف تلقائي لكل انواع الشبكات والراوترات
- يعمل بصمت بالخلفية
- تحويل لـ EXE بضغطة واحدة

## التشغيل السريع

```bash
pip install -r requirements.txt
python run.py --verbose
```

- العميل: http://localhost:8400/client
- لوحة التحكم: http://localhost:8400/admin (admin / admin123)

## بناء EXE

```bash
python build.py
```

أو على ويندوز: انقر مرتين على `build.bat`

الملف يُبنى تلقائياً بدون أسئلة ويكون بمجلد `dist/HelenWiFi.exe`

## هيكل المشروع

```
├── run.py              # نقطة التشغيل
├── build.py            # بناء EXE (ضغطة واحدة)
├── build.bat           # بناء EXE (ويندوز - نقر مرتين)
├── config.py           # الاعدادات
├── requirements.txt    # المتطلبات
├── server/
│   ├── bro_server.py   # السيرفر الرئيسي
│   └── signaling.py    # WebRTC signaling
├── network/
│   └── detector.py     # كشف الشبكة
├── mesh/
│   └── mesh_node.py    # شبكة Mesh
├── templates/
│   ├── admin.html      # لوحة التحكم
│   ├── client.html     # واجهة الاتصال
│   └── login.html      # تسجيل الدخول
└── static/
    └── js/
        └── socket.io.min.js
```

## الشبكات المدعومة

WiFi, Ethernet, DSL, ADSL, VDSL, Fiber, GPON, EPON, Cable, 4G, LTE, 5G, Cellular, VPN, WireGuard, PPPoE, Bridge وكل انواع الراوترات.
