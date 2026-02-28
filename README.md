# هيلين WiFi - Helen WiFi v2.0

سيرفر اتصالات كامل يعمل على **جميع** أنواع الراوترات والكوابل بما فيها الألياف الضوئية (Fiber Optic).

## المميزات (100%)

- **مكالمات صوتية وفيديو** (WebRTC) مع TURN fallback + ICE restart + مراقبة جودة
- **محادثات فورية** - عامة + خاصة + مؤشر كتابة + وصول/قراءة + رسائل أوفلاين
- **مشاركة شاشة** - مشاركة الشاشة مباشرة أثناء المكالمة
- **مشاركة ملفات** - حجم غير محدود + شريط تقدم + سحب وإفلات + رفع متعدد + رفع مجزأ قابل للاستكمال
- **شبكة Mesh** - حتى 100+ سيرفر + TCP fallback + تشفير HMAC + إعادة اتصال تلقائية
- **لوحة تحكم كاملة** - مراقبة مباشرة + معلومات الفايبر + الراوترات المدعومة
- **بناء EXE** - متعدد المنصات (Windows/Linux/macOS)
- **دعم شامل للشبكات** - يعمل على أي راوتر أو كابل

## الراوترات المدعومة

### ألياف ضوئية (Fiber Optic)
FTTH | FTTB | FTTP | FTTC | FTTN | FTTx | GPON | EPON | XG-PON | XGS-PON | 10G-EPON | NG-PON2

### موديولات ضوئية
SFP | SFP+ | SFP28 | QSFP | QSFP+ | QSFP28 | XFP | CFP

### أجهزة شبكات ضوئية
ONT (Optical Network Terminal) | ONU (Optical Network Unit) | OLT (Optical Line Terminal) | Fiber Gateway | Fiber Edge Router | Carrier Fiber Router | Optical Network Router

### أنواع أخرى
WiFi | Ethernet | DSL | ADSL | VDSL | 4G/LTE | 5G NR | VPN | WireGuard | OpenVPN | IPsec | PPPoE | Bridge | Bond | USB Tethering | Satellite | InfiniBand

## التشغيل السريع

```bash
pip install -r requirements.txt
python run.py --verbose
```

- العميل: http://localhost:8400/client
- لوحة التحكم: http://localhost:8400/admin (admin / admin123)

## بناء EXE

```bash
python build.py                  # كشف تلقائي للمنصة
python build.py --platform win   # بناء لويندوز
python build.py --platform linux # بناء للينكس
python build.py --platform mac   # بناء لماك
```

أو على ويندوز: انقر مرتين على `build.bat`

## هيكل المشروع

```
├── run.py              # نقطة التشغيل
├── build.py            # بناء متعدد المنصات
├── config.py           # الاعدادات + أنواع الفايبر
├── requirements.txt    # المتطلبات
├── server/
│   ├── bro_server.py   # السيرفر الرئيسي
│   └── signaling.py    # WebRTC + مشاركة شاشة + ICE restart
├── network/
│   └── detector.py     # كشف الشبكة + كل أنواع الفايبر
├── mesh/
│   └── mesh_node.py    # شبكة Mesh + TCP fallback + تشفير
├── templates/
│   ├── admin.html      # لوحة التحكم + مراقبة الفايبر
│   ├── client.html     # واجهة الاتصال الكاملة
│   └── login.html      # تسجيل الدخول
└── static/
    └── js/
        └── socket.io.min.js
```
