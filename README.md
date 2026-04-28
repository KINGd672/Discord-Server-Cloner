# Discord Full System Bot (Arabic)

بوت ديسكورد متكامل (إدارة + حماية + تذاكر + اقتراحات + سجل أحداث) مبني بـ `discord.py`.

## المميزات

- نظام إدارة متكامل:
  - `kick` / `ban` / `timeout` / `clear`
- نظام التحذيرات:
  - `warn` / `warnings` / `unwarn`
- نظام التذاكر عبر أزرار:
  - إنشاء تذكرة خاصة لكل عضو
  - زر إغلاق التذكرة
- نظام الترحيب والـ Auto Role
- نظام Log للأحداث (حذف/تعديل الرسائل + دخول/خروج الأعضاء)
- نظام الاقتراحات مع تفاعلات 👍👎
- أوامر مساعدة ومعلومات (`help`, `ping`, `userinfo`, `serverinfo`)

## المتطلبات

- Python 3.10+

## التثبيت

```bash
pip install -r requirements.txt
```

## الإعداد

1. انسخ الملف:

```bash
cp config.example.json config.json
```

2. افتح `config.json` وضع:
   - `token` الخاص بالبوت
   - `prefix` (مثل `!`)
   - (اختياري) أي IDs للقنوات/الرول

## التشغيل

```bash
python main.py
```

## أوامر سريعة

- `!help`
- `!setup welcome_channel_id <id>`
- `!setup log_channel_id <id>`
- `!setup auto_role_id <id>`
- `!setup ticket_category_id <id>`
- `!ticketpanel`

> ملاحظة: لازم البوت يكون عنده الصلاحيات المناسبة في السيرفر (Manage Channels, Manage Roles, Moderate Members, Ban/Kick).
