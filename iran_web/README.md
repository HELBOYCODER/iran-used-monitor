# دست‌دوم‌بان — رابط مستقل
Backend باید این پوشه را در ریشه سایت سرو کند. فایل ورودی index.html و دارایی‌های app.js و style.css هستند. بدون build، CDN، npm و وابستگی شبکه‌ای برای پوسته. تصاویر آگهی ممکن است از URL معتبر سرویس بارگذاری شوند؛ CSP backend باید سیاست موردنظر تصاویر را تعیین کند.

## API
همه درخواست‌ها same-origin در /api هستند. توکن Bearer فقط در حافظه صفحه می‌ماند؛ پس از refresh باید دوباره وارد شود. GET health، sources، watches، items، settings، notifications؛ POST watches و scan؛ PUT/DELETE watches/{id}؛ PATCH notifications/{id} با {read:true} و PATCH settings با boolهای scheduler_enabled و ai_enabled. پاسخ آرایه مستقیم و wrapper هم‌نام پشتیبانی می‌شود. اسکن تا 90 ثانیه فرصت پاسخ دارد، باقی درخواست‌ها 20 ثانیه.

اسکن کلی محدودیت backend دارد و تضمین اجرای همه پایش‌ها نیست. برای کنترل دقیق از دکمه اسکن هر پایش استفاده کنید. زمان‌بندی از تنظیمات فعال می‌شود. منابع آزمایشی بدون فعال‌سازی در سرویس، متصل فرض نمی‌شوند. منابع با unknown/unchecked/unsupported/error نیز نمایش داده می‌شوند. شهر و بازه قیمت ورودی کاربر است، اعتبار نهایی بر عهده backend است. قیمت‌ها با فرض قرارداد تومان نمایش داده می‌شوند.

## آزمون
از ریشه مخزن:
```
node --check iran_web/app.js
python3 -m unittest discover -s iran_web/tests
python3 iran_web/tests/fixture_server.py
```
سرور آخر فقط fixture محلی در http://127.0.0.1:8768 است؛ داده‌های آن صرفاً در tests هستند و app.js هیچ داده ساختگی ندارد. آن را در تولید اجرا نکنید.

آزمون مرورگر با fixture: ساخت/ویرایش/توقف/حذف پایش، اسکن، جست‌وجو و empty، ورود توکن، خواندن اعلان و PATCH تنظیمات، رشته تزریق HTML و URL javascript بررسی شد. نمایش اولیه موبایل 412 و دسکتاپ 1440 بدون overflow مشاهده شد. آزمون axe یا screen reader انجام نشده؛ ادعای انطباق رسمی WCAG نداریم. تست خودکار پایتون ساختار، منابع محلی، CSP inline، شناسه‌ها، API و نبود DOM sinkهای ناامن را کنترل می‌کند.
