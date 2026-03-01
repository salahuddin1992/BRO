# هيلين WiFi - Helen WiFi

منصة اتصالات داخلية متكاملة: مكالمات صوت/فيديو + مشاركة شاشة + دردشة مشفرة + ملفات + Mesh.
لا يعتمد على أي خدمة خارجية - يعمل بالكامل على الشبكة المحلية بدون إنترنت.

## المميزات

### الاتصالات
- مكالمات صوتية وفيديو (WebRTC)
- مشاركة الشاشة (Screen Sharing)
- تسجيل المكالمات (Call Recording)
- دردشة فورية (عامة + خاصة + غرف)
- تشفير الرسائل من طرف لطرف (E2E Encryption - ECDH + AES-GCM)

### إدارة الملفات
- مشاركة ملفات مع شريط تقدم (حتى 100MB)
- سحب وإسقاط للرفع
- معاينة الصور مباشرة

### الشبكة
- شبكة Mesh بين السيرفرات (UDP Discovery)
- يدعم جميع الراوترات (WiFi/Ethernet/DSL/Fiber/GPON/EPON/SFP/ONT/ONU)
- كشف تلقائي لواجهات الشبكة

### الإدارة
- لوحة تحكم كاملة مع إحصائيات مباشرة
- نظام صلاحيات متقدم (مدير / مشرف / مستخدم)
- نسخ احتياطي واستعادة
- إدارة المستخدمين (حظر / طرد / حذف / إعادة كلمة مرور)

### تطبيق سطح المكتب
- تطبيق Electron أصلي (نافذة مستقلة)
- أيقونة System Tray مع إشعارات
- تصغير لشريط المهام
- إشعارات النظام الأصلية
- بناء exe بضغطة واحدة (PyInstaller)

### إعدادات مرئية
- ثيم داكن / فاتح
- حجم الخط قابل للتعديل
- تحكم بالإشعارات والأصوات
- إعدادات التشفير والمكالمات

## التشغيل

### الطريقة السريعة (Python)
```bash
pip install -r requirements.txt
python run.py --verbose
```

### تطبيق سطح المكتب (Electron)
```bash
cd electron
npm install
npm start
```

### الروابط
- العميل: http://localhost:8400/client
- الأدمن: http://localhost:8400/admin (admin / admin123)

## بناء التطبيق

### بناء ملف exe (PyInstaller)
```bash
python build.py server
```

### بناء تطبيق Electron
```bash
python build.py all
```

### بناء Electron فقط
```bash
python build.py electron
```

## المتطلبات

### Python
- Python 3.8+
- Flask, Flask-SocketIO, Flask-CORS
- Eventlet

### Electron (اختياري)
- Node.js 18+
- npm

## البنية

```
├── run.py              # نقطة البداية
├── config.py           # الإعدادات
├── build.py            # نظام البناء
├── server/             # سيرفر Flask + WebRTC
├── database/           # قاعدة بيانات SQLite
├── mesh/               # شبكة Mesh
├── network/            # كشف الشبكة
├── templates/          # واجهات HTML
├── static/             # ملفات ثابتة
└── electron/           # تطبيق سطح المكتب
    ├── main.js         # العملية الرئيسية
    ├── preload.js      # جسر الأمان
    └── package.json    # تبعيات Electron
```
