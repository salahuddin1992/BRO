# هيلين WiFi - Helen WiFi

منصة اتصالات داخلية متكاملة: مكالمات صوت/فيديو + مشاركة شاشة + دردشة مشفرة + ملفات + Mesh.
لا يعتمد على أي خدمة خارجية - يعمل بالكامل على الشبكة المحلية بدون إنترنت.

## المميزات

### الاتصالات
- مكالمات صوتية وفيديو (WebRTC) مع ICE restart وتعافي تلقائي
- مشاركة الشاشة (Screen Sharing)
- تسجيل المكالمات (Call Recording)
- دردشة فورية (عامة + خاصة + غرف)
- تشفير الرسائل من طرف لطرف (E2E Encryption - ECDH + AES-GCM)
- ردود الفعل بالرموز التعبيرية (Emoji Reactions)
- مؤشر الكتابة (Typing Indicator)
- الرد على الرسائل (Reply to Messages)
- رسائل بدون اتصال (Offline Messages) - يتم تسليمها عند الاتصال
- غرف صوتية دائمة (Persistent Voice Rooms) مع كتم الصوت
- مكالمات جماعية (Group Calls) - حتى 20 مشترك عبر SFU
- بحث نص كامل في الرسائل (FTS5 Full-Text Search)

### إدارة الملفات
- مشاركة ملفات مع شريط تقدم (حتى 100MB)
- رفع بأجزاء (Chunked Upload) للملفات الكبيرة
- سحب وإسقاط للرفع
- معاينة الصور مباشرة مع صور مصغرة (Thumbnails)
- تشفير الملفات عند الرفع (AES-256-GCM) مع فك التشفير عند التحميل
- ضغط الملفات (Zstandard Compression)
- نظام حصص تخزين للمستخدمين (User Quotas - 500MB افتراضي)
- بحث في الملفات مع تصفية بالتاريخ والمرفِع والغرفة
- انتهاء صلاحية الملفات (TTL) مع تنظيف تلقائي
- التحقق من نوع MIME (python-magic)

### الشبكة
- شبكة Mesh بين السيرفرات (UDP Discovery + HMAC-SHA256)
- WebSocket Mesh Bridge مع HMAC Challenge-Response
- يدعم جميع الراوترات (WiFi/Ethernet/DSL/Fiber/GPON/EPON/SFP/ONT/ONU)
- كشف تلقائي لواجهات الشبكة (جميع الأنواع)
- اكتشاف الخدمات عبر mDNS/Zeroconf
- سيرفر STUN/TURN محلي كامل (UDP/TCP/TLS) مع REST API credentials
- SFU (Selective Forwarding Unit) لمكالمات جماعية موثوقة
- سيرفر SSH للتحكم عن بعد (المدراء والمشرفين)
- سيرفر FTP لنقل الملفات
- سيرفر SFTP لنقل آمن عبر SSH

### الأمان
- تشفير E2E: ECDH (SECP256R1) + AES-256-GCM مع AAD
- TLS تلقائي مع شهادات ذاتية + HSTS
- حماية من XSS (markupsafe)
- حماية Path Traversal (realpath check) على جميع مسارات الملفات والصور المصغرة
- حماية CSRF لعمليات الأدمن
- Rate Limiting: 200 طلب/دقيقة + حد رسائل 10/2 ثواني
- حماية Brute Force: 5 محاولات/60 ثانية لكل IP
- تنظيف تلقائي للتوكنات والجلسات المنتهية
- التحقق من MIME للملفات المرفوعة (حظر الملفات التنفيذية)
- رؤوس أمان كاملة (CSP, X-Frame-Options, X-Content-Type-Options, etc.)
- CORS مقيد للشبكات الخاصة فقط
- Thread-safe: أقفال على `clients` و `auth_tokens`
- لا مستخدمين افتراضيين - التسجيل مطلوب

### الإدارة
- لوحة تحكم كاملة مع إحصائيات مباشرة
- نظام صلاحيات متقدم (مدير / مشرف / مستخدم) مع واجهة لتغيير الصلاحيات
- نسخ احتياطي واستعادة (مع نسخ أمان تلقائي قبل الاستعادة)
- إدارة المستخدمين (حظر / طرد / حذف / إعادة كلمة مرور)
- إدارة الغرف والرسائل والملفات والتسجيلات
- إعدادات السيرفر من لوحة التحكم
- تنظيف تلقائي: ملفات يتيمة + ملفات منتهية + جلسات + أجزاء رفع متروكة

### المراقبة والصحة
- نقطة فحص صحة (`/api/health`)
- مقاييس Prometheus (`/api/metrics`) - CPU, ذاكرة, قرص, مستخدمين, رسائل
- مراقبة موارد النظام (CPU, ذاكرة, قرص, شبكة)
- تشخيصات WebRTC وسجلات المكالمات
- إحصائيات TURN و SFU

### تطبيق سطح المكتب
- تطبيق Electron أصلي (نافذة مستقلة)
- أيقونة System Tray مع إشعارات
- تصغير لشريط المهام
- إشعارات النظام الأصلية
- Deep linking (`bro://`)
- بناء exe بضغطة واحدة (PyInstaller)

### إعدادات مرئية
- ثيم داكن / فاتح
- حجم الخط قابل للتعديل
- تحكم بالإشعارات والأصوات
- إعدادات التشفير والمكالمات
- دعم العربية والإنجليزية (i18n)
- PWA مع Service Worker للعمل دون اتصال

## التشغيل

### الطريقة السريعة (Python)
```bash
pip install -r requirements.txt
python run.py --verbose
```

### Docker
```bash
docker-compose up -d
```

### تطبيق سطح المكتب (Electron)
```bash
cd electron
npm install
npm start
```

### الروابط
- العميل: http://localhost:8400/client
- الأدمن: http://localhost:8400/admin
- فحص الصحة: http://localhost:8400/api/health
- مقاييس Prometheus: http://localhost:8400/api/metrics

> ⚠️ عند أول تشغيل، يجب التسجيل لإنشاء حساب. لا توجد حسابات افتراضية.

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

## الاختبارات
```bash
pytest tests/ -v
```

## المتطلبات

### Python
- Python 3.8+
- Flask, Flask-SocketIO, Flask-CORS
- Eventlet (أو Gevent كبديل)
- cryptography, paramiko, pyftpdlib
- Pillow, psutil, APScheduler, zeroconf

### Electron (اختياري)
- Node.js 18+
- npm

### Docker (اختياري)
- Docker 20+
- Docker Compose 3.8+

## المنافذ

| المنفذ | البروتوكول | الاستخدام |
|--------|-----------|----------|
| 8400 | HTTP/WS | الواجهة الرئيسية + WebSocket |
| 8401 | UDP | اكتشاف Mesh |
| 8402 | TCP | WebSocket Mesh Bridge |
| 3478 | UDP/TCP | STUN/TURN |
| 5349 | TCP/TLS | TURN الآمن |
| 2222 | TCP | SSH |
| 2121 | TCP | FTP |
| 2223 | TCP | SFTP |

## البنية

```
├── run.py              # نقطة البداية
├── config.py           # الإعدادات
├── build.py            # نظام البناء
├── Dockerfile          # Docker deployment
├── docker-compose.yml  # Docker Compose
├── server/             # سيرفر Flask + WebRTC
│   ├── bro_server.py   # السيرفر الرئيسي
│   └── signaling.py    # WebRTC signaling
├── database/           # قاعدة بيانات SQLite + FTS5
├── mesh/               # شبكة Mesh
├── network/            # كشف الشبكة + TURN + SFU + SSH + FTP + SFTP
├── utils/              # تشفير + ضغط + إشعارات + مراقبة + جدولة
├── templates/          # واجهات HTML
├── static/             # ملفات ثابتة + JS + PWA
├── tests/              # اختبارات pytest
└── electron/           # تطبيق سطح المكتب
    ├── main.js         # العملية الرئيسية
    ├── preload.js      # جسر الأمان
    └── package.json    # تبعيات Electron
```
