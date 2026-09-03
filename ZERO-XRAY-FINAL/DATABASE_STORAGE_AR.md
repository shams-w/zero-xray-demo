# مكان حفظ بيانات ZERO X-RAY

بيانات التشغيل لم تعد مرتبطة بفولدر الـ ZIP.

على Windows ومع وجود قرص D، المسار الافتراضي هو:

`D:\ZERO-XRAY-DATA\runtime.db`

والملفات التي ترفعها الجهات تحفظ في:

`D:\ZERO-XRAY-DATA\tenant_files\`

لذلك إذا فككت نسخة ZIP جديدة وشغلتها، ستستخدم نفس قاعدة البيانات بدل البدء من الصفر.

## مشاهدة البيانات بسهولة

شغّل الملف:

`VIEW_DATABASE.bat`

سيتم إنشاء مجلد:

`D:\ZERO-XRAY-DATA\database_view\`

وبه CSV منفصل لكل جدول مثل:

- tenants.csv
- platform_users.csv
- services.csv
- analyses.csv
- blueprints.csv
- agents.csv
- data_sources.csv
- integrations.csv
- customers.csv
- journeys.csv
- journey_events.csv
- audit_log.csv

هذه ملفات للعرض فقط. قاعدة البيانات الحقيقية التي يستخدمها النظام هي `runtime.db`.
