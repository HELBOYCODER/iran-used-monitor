# پل وب‌سایت به JSON برای بازارهای ایران

## ابزار واقعاً بررسی‌شده

در ۸ نوامبر ۲۰۲۶، ابتدا `cli-hub`، `cli-anything` و `cli_anything` در PATH موجود نبودند. مهارت leanrea و API design خوانده شد. سایت رسمی https://clianything.cc/ و `/llms.txt` مشخص می‌کند CLI-Anything یک رجیستری/مدیر CLI و روش ساخت harness است، نه سرویس جادویی تبدیل هر وب‌سایت به API.

بسته رسمی `cli-anything-hub==0.4.1` در محیط ایزوله `/var/minis/workspace/cli-anything-env` نصب و واقعاً اجرا شد:

```sh
/var/minis/workspace/cli-anything-env/bin/cli-hub --version
/var/minis/workspace/cli-anything-env/bin/cli-hub search iran
/var/minis/workspace/cli-anything-env/bin/cli-hub search website
/var/minis/workspace/cli-anything-env/bin/cli-hub search scraping
```

برای iran و scraping نتیجه‌ای نبود؛ website فقط AnyGen (تولید سایت با API ابری) را برگرداند که مناسب این کار نیست. بنابراین اتصال بازار ایرانی توسط harness سفارشی این پروژه انجام می‌شود؛ ادعای وجود افزونه آماده CLI-Anything یا تولید خودکار توسط آن نداریم. نصب هاب و جستجوی رجیستری واقعاً انجام شده است.

REA نسخه 6.8.0 از قبل در `/usr/local/bin/rea` موجود بود. `rea inspect-artifact` واقعاً روی یک chunk عمومی کمدا اجرا شد؛ شاهد `ev_9d63ffb8d1ee1a258bfe7a5f0cec08e87522633f1e40c68ef203085d38112608` و SHA256 برابر `f6a45bc79b1994d85e8856425b45afb7d94b6c0c15b47dc9688ccaea3085a968` است. این فقط مشاهده فایل JavaScript است؛ کشف کامل شبکه اجرا یا اثبات API از روی این chunk نیست. تحلیل runtime توسط REA به CDP واقعی نیاز دارد و در این کار ادعای اجرای آن نداریم.

## قرارداد CLI

`tools/iran_market_cli.py` فقط کتابخانه استاندارد پایتون مصرف می‌کند و از `iran_monitor.sources.scan_source(watch)` و `iran_monitor.core.matches` استفاده می‌کند. تغییر یا کپی adapterهای بک‌اند انجام نشده است.

```sh
python3 tools/iran_market_cli.py sources
IRAN_MONITOR_EXPERIMENTAL_SOURCES=1 python3 tools/iran_market_cli.py search --source esam --query لپتاپ --count-only
```

پیش از ادغام بک‌اند در همین checkout، مسیر آن صریحاً معرفی شود؛ sibling به‌صورت پنهانی import نمی‌شود:

```sh
IRAN_MONITOR_EXPERIMENTAL_SOURCES=1 python3 tools/iran_market_cli.py --backend-root /var/minis/workspace/iran-backend search --source komodaa --query لباس --city tehran --min-price 100000 --max-price 5000000 --limit 20 --count-only
```

دستور sources فقط قابلیت adapterها را اعلام می‌کند، نه سلامت زنده آنها. خروجی search یک شیء JSON با schema_version برابر 1 است؛ خطاها نیز JSON هستند. exit code موفقیت 0، خطای ورودی/بالادست 2 و خطای داخلی 3 است. help معمول argparse متن است.

قیمت‌ها تومان (`TMN`) هستند. query به‌صورت محلی هم تطبیق داده می‌شود. esam و komodaa فقط نمونه صفحه اول هستند؛ شهر نامشخص است، جستجوی جامع یا فیلتر واقعی شهر ادعا نمی‌شود. `fetched_count` تعداد کارت‌های parseشده، `matched_count` تعداد تطبیق‌های یکتا و `returned_count` تعداد کارت‌های خروجی است. `--count-only` همه جزئیات کارت‌ها را حذف می‌کند. فیلدهای خروجی محدود به source/title/price/url/image/city/description هستند؛ شناسه کاربر، نام فروشنده، شماره تلفن و پاسخ خام forward نمی‌شوند. متن کارت‌های عمومی HTML ممکن است اطلاعاتی داشته باشد که خود آگهی‌دهنده در عنوان گذاشته؛ تضمین حذف همه اطلاعات شخصی در متن آزاد داده نمی‌شود.

## شاهد زنده و محدودیت شبکه Minis

دو URL عمومی بدون کوکی، لاگین یا پرداخت با curl پاسخ 200 دادند:

- `https://api.esam.ir/api/items/v2/GetItemList?pageNumber=1`: ده ردیف
- `https://search.komodaa.com/api/v2.6/search/products`: هجده ردیف

اما اتصال مستقیم از fetch امن بک‌اند در همین دستگاه `unreachable` داد. علت مشاهده‌شده: DNS محیط برای دو دامنه آدرس‌های synthetic از 198.19.0.0/16 و 2001:2:: برمی‌گرداند و `ipaddress.is_global` آنها False است. fetch بک‌اند عمداً مقصد غیرعمومی را رد می‌کند. این خطای ایمنی را دور نزدیم و فایل همکار را تغییر ندادیم. موفقیت curl به معنی موفقیت transport امن production نیست.

برای تبدیل واقعی پاسخ عمومی در این محیط، curl را صرفاً به‌عنوان دریافت دستی قابل‌ممیزی استفاده کرده و فایل محلی را وارد parser موجود کردیم؛ CLI این حالت را صریحاً `transport=local_capture` علامت می‌زند. این روش ادعای اتصال زنده بک‌اند نمی‌کند و هیچ قابلیت curl یا تغییر DNS در سرور/API اضافه نمی‌کند:

```sh
curl --fail --silent --show-error --max-time 25 'https://api.esam.ir/api/items/v2/GetItemList?pageNumber=1' -o /tmp/esam-public.json
python3 tools/iran_market_cli.py --backend-root /var/minis/workspace/iran-backend search --source esam --query ا --input-json /tmp/esam-public.json --count-only
curl --fail --silent --show-error --max-time 25 'https://search.komodaa.com/api/v2.6/search/products' -o /tmp/komodaa-public.json
python3 tools/iran_market_cli.py --backend-root /var/minis/workspace/iran-backend search --source komodaa --query ا --input-json /tmp/komodaa-public.json --count-only
```

نتیجه مشاهده‌شده: ایسام fetched=10 و matched=10؛ کمدا fetched=18 و matched=15؛ در هر دو returned=0 و items=[] برای حفاظت از جزئیات آگهی. ورودی فایل حداکثر 2 MiB است و فقط قالب عمومی esam/komodaa را می‌پذیرد. این ورودی آفلاین نیاز به فعال‌سازی fetch آزمایشی ندارد، زیرا شبکه‌ای درخواست نمی‌کند.

همکار بک‌اند سپس حالت صریح `IRAN_MONITOR_USE_ENV_PROXY=1` را اضافه کرد؛ CLI بدون تغییر آن را مصرف می‌کند. آزمون مجدد با این فلگ `not_configured` برگرداند: نام‌های HTTPS_PROXY و https_proxy در محیط حاضر بودند اما مقدار هر دو خالی بود (فقط خالی/غیرخالی بررسی شد، هیچ مقدار محرمانه چاپ نشد). بنابراین تا زمان تنظیم واقعی پراکسی مورداعتماد، موفقیت transport زنده ادعا نمی‌شود. راه production، DNS عمومی واقعی یا پراکسی معتبر با پذیرش صریح مرز اعتماد توسط اپراتور است؛ حذف کنترل SSRF یا مجاز کردن عمومی رنج synthetic پیشنهاد نمی‌شود. هیچ endpoint تماس، login، captcha bypass، کوکی کاربر یا داده فروشنده مصرف نشده است.

## نتیجه اتصال زنده پس از یکپارچه‌سازی

پس از تشخیص ناسازگاری شبکه synthetic با IP pinning، گزینه صریح `IRAN_MONITOR_TRUST_SYSTEM_DNS=1` در بک‌اند اضافه شد. این حالت فقط چهار دامنه ثابت بازارهای ساخته‌شده را می‌پذیرد، از HTTPS استاندارد با رد redirect استفاده می‌کند و برای خوراک/AI دلخواه قابل استفاده نیست. کنترل پین IP پیش‌فرض تغییر نکرده است؛ این استثنا اعتماد به DNS میزبان را لازم دارد.

آزمون واقعی از پل در ۸ نوامبر ۲۰۲۶، نه از فایل capture:

```sh
IRAN_MONITOR_TRUST_SYSTEM_DNS=1 IRAN_MONITOR_EXPERIMENTAL_SOURCES=1 python3 tools/iran_market_cli.py search --source esam --query ا --count-only
IRAN_MONITOR_TRUST_SYSTEM_DNS=1 IRAN_MONITOR_EXPERIMENTAL_SOURCES=1 python3 tools/iran_market_cli.py search --source komodaa --query ا --count-only
```

- ایسام: `ok=true`, `transport=backend_live`, `fetched_count=10`, `matched_count=10`.
- کمدا: `ok=true`, `transport=backend_live`, `fetched_count=18`, `matched_count=16`.
- جزئیات آگهی‌ها در خروجی count-only حذف شد. شمار تطبیق با تغییر خوراک ممکن است تغییر کند.
- این موفقیت، محدودیت نمونه صفحه اول و نامشخص‌بودن شهر را برطرف نمی‌کند.

## آزمون

```sh
python3 -m unittest discover -s tests/bridge -v
```

آزمون‌ها مستقل از pytest/conftest پروژه و بدون درخواست شبکه هستند. قرارداد JSON، داده حداقلی، خطاهای ساختاریافته، اعتبارسنجی، حذف موارد تکراری و count-only بررسی می‌شوند. فایل‌های `iran_monitor/` و `tests/iran/` متعلق به همکار بک‌اند هستند و این شاخه آنها را تغییر نمی‌دهد.
