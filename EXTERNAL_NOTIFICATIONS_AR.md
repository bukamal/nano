# الإشعارات الخارجية — طبقة التوصيل الموحّدة (PHASE 11)

## الفكرة

نظام الإشعارات الداخلي (محرك `NotificationService`) يبقى **المصدر الوحيد للحقيقة**:
نفس القواعد، نفس الحدود، نفس الأولويات (`info`/`warning`/`urgent`)، نفس مفاتيح
إلغاء التكرار (`<rule>:<yyyy-mm-dd>`)، ونفس ساعات الهدوء. الطبقة الخارجية الجديدة
`ExternalNotificationService` لا تعيد حساب أي شيء ولا تخترع تنبيهات جديدة — بل
**تستقبل التنبيهات المولّدة بالفعل** من المحرك الداخلي وتوزّعها على القنوات
الخارجية التي فعّلها المدير (Telegram / بريد إلكتروني / Webhook عام).

بهذا التصميم، التنبيه الذي تراه داخل التطبيق (الجرس) هو نفسه الذي يصل Telegram
أو البريد — لا انحراف بين "داخلي" و"خارجي" أبداً.

## البنية

```
محرك داخلي (NotificationService.generate_alerts)
        │  (نفس القواعد/الأولويات/مفاتيح التكرار/ساعات الهدوء)
        ▼
ExternalNotificationService.dispatch()
        │
        ├─ توجيه لكل نوع تنبيه (rules: rule_key → قنوات)
        ├─ عزل القنوات المعطّلة فقط
        ├─ إعادة محاولة مع تأخير مضاعف (retry/backoff)
        └─ سجل تسليم لكل (dedupe_key, channel) في notification_delivery_log
                │
                ▼
        TelegramProvider / SmtpEmailProvider / WebhookProvider
```

## القنوات المدعومة

| القناة | المفتاح | الإعدادات المطلوبة |
|---|---|---|
| Telegram | `telegram` | `bot_token` (من @BotFather) و `chat_id` (رقم/معرّف المحادثة) |
| بريد إلكتروني | `email` | `smtp_host`, `smtp_port`, `username`, `password`, `to_address`, `use_tls` |
| Webhook عام | `webhook` | `url` (يُرسل JSON بحقول `rule_key/severity/title/body/...`) |

## الإعدادات المخزنة

تُخزَّن كلها في جدول `settings` تحت المفتاح `external_notifications_config`
(JSON واحد يُقرأ/يُكتب ذرياً — نفس نمط `notifications_config`):

```json
{
  "channels": {
    "telegram": {"enabled": false, "bot_token": "", "chat_id": ""},
    "email":   {"enabled": false, "smtp_host": "", "smtp_port": 587,
                "username": "", "password": "", "to_address": "", "use_tls": true},
    "webhook": {"enabled": false, "url": ""}
  },
  "rules": {
    "default": ["telegram", "email", "webhook"]
  },
  "retry": {"max_attempts": 3, "base_delay_seconds": 1.0}
}
```

### التوجيه حسب نوع التنبيه
- `rules.default` = القنوات الافتراضية لكل تنبيه لا يملك توجيهاً خاصاً.
- يمكن كتم نوع معيّن أو توجيهه لقنوات محددة بإضافة مفتاح بنفس اسم `rule_key`،
  مثلاً: `"low_stock": []` يمنع وصول تنبيهات المخزون المنخفض للخارج،
  و`"receivables_overdue": ["telegram"]` يرسل المتأخرات لـ Telegram فقط.
- أنواع التنبيهات الحالية: `receivables_overdue`, `receivables_due_soon`,
  `low_stock`, `backup_missing`, `backup_due`, `license_expiry`, `sales_drop`.

### متغيرات البيئة (بديل للأسرار)
تُقرأ عند `get_config()` وتتغلب على المخزّن (مفيدة للتطوير/CI، والتطبيق المعبأ
على أندرويد يستخدم المخزّن):

| المتغير | يضبط |
|---|---|
| `TELEGRAM_BOT_TOKEN` | `channels.telegram.bot_token` |
| `TELEGRAM_CHAT_ID` | `channels.telegram.chat_id` |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USERNAME` / `SMTP_PASSWORD` / `SMTP_TO_ADDRESS` | إعدادات البريد |
| `NOTIFY_WEBHOOK_URL` | `channels.webhook.url` |

## الإعداد عبر الكود (أو من واجهة إدارية مستقبلاً)

```python
ext = ctx.external_notifications
ext.set_channel("telegram", enabled=True, bot_token="123:ABC", chat_id="-100...")
ext.set_channel("email", enabled=True, smtp_host="smtp.gmail.com", username="you@gmail.com",
                password="app-password", to_address="you@gmail.com")
ext.save_config({"rules": {"low_stock": [], "default": ["telegram", "email"]}})

# إرسال تنبيه تجريبي عبر قناة حقيقية:
result = ext.test_channel("telegram")
print(result.ok, result.error)
```

## سلوك التسليم

- **إلغاء التكرار**: سطر واحد في `notification_delivery_log` لكل
  `(dedupe_key, channel)`. التنبيه الذي سُلّم اليوم لن يُرسل ثانية من أي مسار
  (داخلي، خارجي، أو Dart في الخلفية) — نفس الاتفاقية التي يستخدمها
  `notification_log`.
- **إعادة المحاولة**: `max_attempts` محاولات بتأخير `base_delay * 2^(n-1)`.
- **سجل الفشل**: محاولات فاشلة تُسجَّل `failed` مع `attempts` و`error`، وتُعاد
  المحاولة تلقائياً في الدفعة التالية.
- **ساعات الهدوء**: تُقرأ من `notifications_config.quiet_hours` (نفس إعداد
  المحرك الداخلي وDart) — أثناءها تتوقف كل عمليات الإرسال الخارجي.
- **لا يمنع التشغيل أبداً**: أي فشل قناة يُحتجز داخل الطبقة ولا يكسر التطبيق.

## نقاط الربط

- `AppContext` يملك الآن `external_notifications` (يُبنى تلقائياً بعد
  `NotificationService`).
- `main.py` يستدعي `ctx.external_notifications.dispatch_async()` عند تشغيل
  التطبيق (best-effort) ليدفع أي تنبيهات معلّقة وُجدت والتطبيق مغلق.
- أي مكان يريد إرسالاً فورياً يمكنه استدعاء `dispatch()` مباشرة.

## قاعدة البيانات (الترحيل)

- `SCHEMA_VERSION` ارتفع من 14 إلى 15.
- جدول جديد `notification_delivery_log` (يُنشأ بـ `CREATE TABLE IF NOT EXISTS`
  — لا تغيير مدمر على قواعد بيانات قائمة).

## الاختبار

```bash
PYTHONPATH=src python3 tools/external_notification_dispatch_test.py
```

يعمل دون إنترنت: يسجّل سيناريو حقيقي (صنف منخفض + فاتورة متأخرة 40 يوماً)،
يولّد التنبيهات عبر المحرك الداخلي نفسه، يمررها عبر التوجيه/إعادة المحاولة/
السجل، ويتحقق من إلغاء التكرار والتوجيه حسب النوع وإعادة محاولة الفشل.

---

## تحديث v0.9.1 — شاشة إعدادات في التطبيق + إرسال فوري

- أُضيف قسم "الإرسال الخارجي" إلى شاشة الإشعارات الذكية نفسها: تفعيل تيليغرام / البريد / Webhook، إدخال التوكنات (تُحفظ في جدول settings محليًا — لا أسرار في الكود)، زر "اختبار القناة" لكل قناة، ولوحة "توزيع القنوات حسب نوع التنبيه" (8 أنواع).
- الإرسال الفوري: لحظة توليد تنبيه جديد داخليًا (NotificationService.sync) يُدفع فورًا عبر القنوات المفعّلة من خيط خلفي (daemon thread) — لا ينتظر تشغيل التطبيق القادم، ولا يمنع واجهة التطبيق أبدًا، ويحترم نفس ساعات الهدوء وسجل الرفض (notification_delivery_log).
- الاختبارات: `external_notification_dispatch_test.py` (الطبقة) + `external_immediate_hook_test.py` (الربط الفوري).
