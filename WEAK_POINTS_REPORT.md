# Helen WiFi - تقرير نقاط الضعف (Weak Points Report)

**التاريخ:** 2026-03-04
**نتيجة الاختبارات:** 166 نجاح | 3 تخطي | 0 فشل

---

## ملخص: نسبة جاهزية الاتصالات

| المكون | النسبة | الحالة |
|--------|--------|--------|
| WebRTC Signaling (ACK/Retry) | 95% | يعمل مع نقاط ضعف بسيطة |
| TURN/STUN Server | 90% | يعمل لكن بدون TLS افتراضياً |
| mDNS Discovery | 85% | يعمل مع مشاكل في eventlet |
| Mesh UDP Discovery | 90% | يعمل لكن بدون تشفير UDP |
| WebSocket Mesh Bridge | 90% | يعمل لكن السر يُرسل كنص صريح |
| SFU Media Relay | 85% | Signaling فقط، بدون forwarding فعلي |
| E2E Encryption | 95% | يعمل بشكل جيد |
| Database | 98% | يعمل بشكل ممتاز |
| Electron Desktop | 90% | يعمل لكن بدون CSP |

**التقييم العام للاتصالات: ~90%** - المشروع يعمل بشكل طبيعي للاتصالات على الشبكة المحلية

---

## نقاط الضعف التفصيلية

---

### 1. كلمة مرور المدير الافتراضية (خطورة: عالية)
**الملف:** `config.py:41`
**النسبة:** 70%

```python
ADMIN_USERNAME = os.environ.get("BRO_ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("BRO_ADMIN_PASS", "admin123")
```

**السبب:** كلمة المرور الافتراضية `admin123` ضعيفة جداً. أي شخص على الشبكة المحلية يمكنه الوصول للوحة التحكم بسهولة.

**الحل:** إجبار المستخدم على تغيير كلمة المرور عند أول تشغيل.

---

### 2. CORS مفتوح بالكامل (خطورة: متوسطة)
**الملف:** `server/bro_server.py`
**النسبة:** 75%

```python
CORS(app)  # wildcard origins
```

**السبب:** يسمح لأي موقع ويب بإرسال طلبات للخادم. في بيئة الشبكة المحلية هذا يعني أن أي صفحة ويب مفتوحة على جهاز المستخدم يمكنها التفاعل مع السيرفر.

**الحل:** تحديد الأصول المسموحة فقط (مثلاً `http://localhost:8400`).

---

### 3. عدم وجود TLS/HTTPS افتراضياً (خطورة: متوسطة-عالية)
**الملف:** `network/turn_server.py:219`
**النسبة:** 80%

```python
if self.tls_cert and self.tls_key and os.path.isfile(self.tls_cert):
    # TLS listeners only start if certs exist
```

**السبب:** TURN/TLS لا يعمل إلا إذا وفر المستخدم شهادات TLS يدوياً. بدون TLS:
- حركة TURN تُنقل بدون تشفير
- كلمات المرور المؤقتة تُرسل كنص صريح
- البيانات المنقولة عبر TURN relay يمكن اعتراضها

**الحل:** إنشاء شهادة self-signed تلقائياً عند بدء التشغيل.

---

### 4. Mesh UDP بدون تشفير (خطورة: متوسطة)
**الملف:** `mesh/mesh_node.py:148`
**النسبة:** 80%

```python
def _send_broadcast(self, msg):
    data = msgpack.packb(msg, use_bin_type=True)  # بدون تشفير
    ...
    sock.sendto(data, (addr, self.mesh_port))
```

**السبب:** رسائل الاكتشاف عبر UDP تُرسل بدون تشفير. يمكن لأي جهاز على الشبكة:
- رؤية إعلانات السيرفرات
- إرسال إعلانات مزيفة (spoofing)
- اعتراض قائمة المستخدمين أثناء المزامنة

**الحل:** إضافة HMAC signature لرسائل UDP والتحقق منها عند الاستقبال.

---

### 5. WebSocket Mesh يرسل Secret Key كنص صريح (خطورة: متوسطة)
**الملف:** `network/ws_mesh.py:172-175`
**النسبة:** 80%

```python
self._send_frame(sock, {
    "secret": self.secret_key,  # المفتاح السري يُرسل كنص صريح
    "server_id": self.server_id,
})
```

**السبب:** عند اتصال mesh peer، المفتاح السري يُرسل عبر TCP بدون TLS. يمكن اعتراضه بسهولة عبر packet sniffing.

**الحل:** استخدام challenge-response بدلاً من إرسال المفتاح مباشرة، أو استخدام TLS للاتصالات.

---

### 6. SFU ليس SFU حقيقي (خطورة: متوسطة)
**الملف:** `network/sfu.py`
**النسبة:** 85%

**السبب:** الـ SFU الحالي هو **signaling relay فقط** وليس media relay حقيقي. هو يعيد توجيه رسائل SDP و ICE بين الأطراف، لكن الميديا الفعلية (صوت/فيديو) تنتقل peer-to-peer أو عبر TURN. في الواقع:
- لا يوجد media forwarding فعلي
- لا يوجد simulcast support
- لا يوجد bandwidth estimation

هذا يعني أن مكالمات المجموعة لا تستفيد من مزايا SFU الحقيقي.

**الحل:** مقبول للإصدار الحالي، لكن المكالمات الجماعية ستعاني من مشاكل scalability مع أكثر من 4-5 مشاركين.

---

### 7. mDNS مع Eventlet conflict (خطورة: متوسطة)
**الملف:** `network/discovery.py:115-117`
**النسبة:** 85%

```python
try:
    info = zc.get_service_info(type_, name)
except RuntimeError:
    # Eventlet monkey-patches can cause "Use AsyncServiceInfo" errors
    info = None
```

**السبب:** Eventlet monkey-patching يتعارض مع Zeroconf، مما يسبب فشل اكتشاف الأجهزة في بعض الحالات. عندما يفشل `get_service_info`، الجهاز المكتشف يُتجاهل بالكامل.

**الحل:** استخدام `AsyncServiceInfo` بدلاً من `get_service_info` العادي، أو تأخير monkey-patching لـ Zeroconf.

---

### 8. 3 اختبارات متخطاة (netifaces) (خطورة: منخفضة)
**الملف:** `tests/test_communications.py`
**النسبة:** 95%

```
TestNetifaces::test_netifaces_import SKIPPED
TestNetifaces::test_netifaces_gateways SKIPPED
TestNetifaces::test_detector_uses_netifaces SKIPPED
```

**السبب:** مكتبة `netifaces` لا تُبنى على بعض الأنظمة (مشاكل compilation). المشروع يتعامل مع هذا بشكل جيد عبر fallback، لكن فقدان netifaces يعني:
- عدم القدرة على كشف gateway الشبكة
- معلومات أقل عن واجهات الشبكة

**الحل:** استبدال `netifaces` بـ `psutil` أو `netifaces2` (fork محدث).

---

### 9. Eventlet مهمل (Deprecated) (خطورة: متوسطة)
**الملف:** `network/ws_mesh.py:16`
**النسبة:** 85%

```
DeprecationWarning: Eventlet is deprecated.
```

**السبب:** Eventlet مهمل رسمياً ولن يتلقى تحديثات أمنية جديدة. المشروع يعتمد عليه بشكل كبير في:
- Flask-SocketIO async
- WebSocket Mesh Bridge
- Green threads للاتصالات المتزامنة

**الحل:** الترحيل إلى `gevent` أو `asyncio` في إصدار مستقبلي.

---

### 10. لا يوجد CI/CD Pipeline (خطورة: متوسطة)
**النسبة:** 70%

**السبب:** لا يوجد GitHub Actions أو أي نظام CI/CD:
- الاختبارات لا تُشغل تلقائياً عند push
- لا يوجد فحص أمني تلقائي
- لا يوجد تحقق من جودة الكود

**الحل:** إضافة GitHub Actions workflow لتشغيل `pytest` تلقائياً.

---

### 11. لا يوجد Content Security Policy في Electron (خطورة: متوسطة)
**الملف:** `electron/main.js`
**النسبة:** 85%

**السبب:** نافذة Electron تحمل محتوى من `http://127.0.0.1:8400` بدون CSP headers. هذا يفتح الباب لـ XSS attacks إذا تمكن مهاجم من حقن HTML/JS.

**الحل:** إضافة CSP header في Flask أو في Electron `webPreferences`.

---

### 12. Mesh HTTP بدون HTTPS (خطورة: متوسطة)
**الملف:** `mesh/mesh_node.py:197-198`
**النسبة:** 80%

```python
url = f"http://{host}:{peer['port']}/api/mesh/sync-users"
requests.post(url, json={...}, headers={"X-Mesh-Secret": config.SECRET_KEY}, timeout=3)
```

**السبب:** اتصالات mesh بين السيرفرات تستخدم HTTP (بدون تشفير). المفتاح السري `X-Mesh-Secret` يُرسل في كل طلب كنص صريح يمكن اعتراضه.

**الحل:** استخدام HTTPS بين mesh peers أو استخدام WebSocket Mesh Bridge (الذي يدعم الضغط على الأقل) بدلاً من HTTP.

---

### 13. حد كلمة المرور ضعيف (خطورة: منخفضة)
**الملف:** `server/bro_server.py`
**النسبة:** 90%

**السبب:** الحد الأدنى لكلمة المرور 4 أحرف فقط، بدون متطلبات تعقيد (أحرف كبيرة، أرقام، رموز).

**الحل:** رفع الحد إلى 6 أحرف على الأقل مع متطلبات تعقيد.

---

## تقييم جاهزية الاتصالات

### المشروع يعمل بنسبة ~90% للاتصالات المحلية

| نوع الاتصال | الحالة | ملاحظات |
|-------------|--------|---------|
| الرسائل النصية | يعمل 100% | بدون مشاكل |
| المكالمات الصوتية 1-to-1 | يعمل 95% | ممتاز مع ICE restart |
| مكالمات الفيديو 1-to-1 | يعمل 95% | ممتاز مع fallback |
| مكالمات المجموعة (3-4) | يعمل 85% | SFU signaling فقط |
| مكالمات المجموعة (5+) | يعمل 60% | لا يوجد SFU حقيقي |
| مشاركة الشاشة | يعمل 90% | يعتمد على WebRTC |
| مشاركة الملفات | يعمل 95% | مع تشفير وضغط |
| اكتشاف الأجهزة (mDNS) | يعمل 85% | تعارض مع eventlet |
| Mesh بين سيرفرات | يعمل 90% | يعمل لكن بدون تشفير |
| التشفير من طرف لطرف | يعمل 95% | ECDH + AES-GCM |

### الخلاصة

المشروع **يعمل بشكل جيد** للاتصالات على الشبكة المحلية. النقاط الضعيفة الرئيسية:

1. **أمنية:** غياب TLS/HTTPS افتراضياً، كلمة مرور admin ضعيفة، CORS مفتوح
2. **تقنية:** Eventlet مهمل، SFU ليس حقيقي، netifaces لا تُبنى
3. **تشغيلية:** لا يوجد CI/CD، لا يوجد CSP

**للاستخدام على شبكة محلية موثوقة** (مثل شبكة شركة أو منزل)، المشروع يعمل بشكل طبيعي وموثوق بنسبة **~90%**.

**للاستخدام في بيئة إنتاج حقيقية** مع مستخدمين غير موثوقين، يجب معالجة نقاط الأمان أولاً (خاصة TLS والكلمات السرية).
