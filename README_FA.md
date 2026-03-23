# گوست‌وایر - تونل معکوس ضد سانسور

**[📖 English](README.md)**

گوست‌وایر یک سیستم تونل معکوس مبتنی بر WebSocket است که به کاربران در کشورهای دارای سانسور کمک می‌کند تا به اینترنت آزاد دسترسی پیدا کنند. این سیستم از اتصالات WebSocket امن روی TLS استفاده می‌کند که تشخیص و مسدود کردن آن دشوار است.

## ویژگی‌ها

- **پشتیبانی از پروتکل‌های متعدد** - WebSocket، HTTP/2 و gRPC

- **احراز هویت رمزگذاری شده با RSA** - توکن برای پروکسی‌های خاتمه‌دهنده TLS (مانند CloudFlare) نامرئی است

- **رمزگذاری سرتاسری AES-256-GCM** - تمام داده‌های تونل با کلیدهای تصادفی ۲۵۶ بیتی رمزگذاری شده‌اند

- **معماری تونل معکوس** - کلاینت به سرور متصل می‌شود (مسدودسازی خروجی را دور می‌زند)

- **جریان دوطرفه** - یک اتصال مداوم روی TLS

- **هدایت پورت TCP انعطاف‌پذیر** - محدوده پورت، اتصال IP، نگاشت‌های سفارشی

- **نبض داخلی** - نگهداشت زنده در لایه انتقال و لایه برنامه

- **سازگار با CloudFlare** - با پروکسی‌های خاتمه‌دهنده TLS (با WebSocket/HTTP/2) کار می‌کند

- **پنل مدیریت وب** - پایش سیستم بلادرنگ، تنظیم تونل، لاگ‌ها، کنترل سرویس

- **معکوس‌پروکسی nginx** - راه‌اندازی آماده تولید با Let's Encrypt

- **فایل‌های باینری کامپایل شده** - Linux amd64 و arm64 (سازگار با Ubuntu 22.04+)

- **سرویس‌های systemd** - شروع خودکار، راه‌اندازی مجدد، لاگ‌نویسی

- **به‌روزرسانی خودکار** - به‌روزرسانی خودکار فایل باینری از طریق انتشارهای GitHub

- **نصب آسان** - اسکریپت‌های راه‌اندازی یک دستوری با تنظیمات تعاملی

## شروع سریع

### مرحله ۱: نصب سرور (کشور دارای سانسور - مثلاً ایران)

سرور در کشور دارای سانسور با IP عمومی اجرا می‌شود که می‌تواند اتصالات ورودی را دریافت کند.

```bash
wget https://raw.githubusercontent.com/frenchtoblerone54/ghostwire/main/scripts/install-server.sh -O install-server.sh
chmod +x install-server.sh
sudo ./install-server.sh
```

**نکته:** توکن احراز هویت را ذخیره کنید - برای کلاینت به آن نیاز دارید!

### مرحله ۲: نصب کلاینت (کشور بدون سانسور - مثلاً هلند، آمریکا)

کلاینت روی یک VPS در کشور بدون سانسور با دسترسی نامحدود به اینترنت اجرا می‌شود.

```bash
wget https://raw.githubusercontent.com/frenchtoblerone54/ghostwire/main/scripts/install-client.sh -O install-client.sh
chmod +x install-client.sh
sudo ./install-client.sh
```

وارد کنید:

- **آدرس سرور** که به سرور ایران شما اشاره می‌کند (مثلاً `wss://iran-server.com/ws`)

- **توکن احراز هویت** از سرور

- کلاینت به سرور ایران متصل می‌شود

### مرحله ۳: استفاده از تونل (در ایران)

کاربران در ایران به پورت‌های محلی سرور (مثلاً `localhost:8080`) متصل می‌شوند و ترافیک از طریق تونل به کلاینت NL هدایت می‌شود که درخواست‌های واقعی اینترنت را انجام می‌دهد.

## مستندات

- **[راهنمای نصب](docs/installation.md)** - دستورالعمل‌های دقیق نصب برای سرور و کلاینت

- **[مرجع تنظیمات](docs/configuration.md)** - گزینه‌های کامل تنظیمات

- **[عیب‌یابی](docs/troubleshooting.md)** - مشکلات رایج و راه‌حل‌ها

- **[امنیت](docs/security.md)** - جزئیات رمزنگاری و ملاحظات امنیتی

## معماری

### تونل معکوس برای دور زدن مسدودسازی خروجی

برای سناریوهایی طراحی شده است که کشورهای دارای سانسور اتصالات خروجی به سرورهای خارجی را مسدود می‌کنند (مثلاً ایران اتصالات به وب‌سایت‌های بین‌المللی را مسدود می‌کند).

#### راه‌اندازی:

- **سرور:** در کشور دارای سانسور (ایران) با IP عمومی اجرا می‌شود

- **کلاینت:** در کشور بدون سانسور (هلند) با دسترسی نامحدود به اینترنت اجرا می‌شود

#### چرا این کار می‌کند؟

- ایران اتصالات خروجی به سرورهای خارجی را مسدود می‌کند

- اما سرور ایران IP عمومی دارد و می‌تواند اتصالات WebSocket ورودی را دریافت کند

- کلاینت NL به سرور ایران متصل می‌شود (ورودی به ایران = مجاز ✅)

- پس از برقراری تونل، ترافیک دوطرفه جریان می‌یابد

#### جریان داده‌ها:

```
[کاربر در ایران] → [سرور localhost:8080] → [سرور ایران]
       ↓ تونل WebSocket
[کلاینت NL] → [اینترنت: پورت 80/443]
```

#### گام به گام:

۱. کلاینت (NL) اتصال WebSocket را به سرور (ایران) آغاز می‌کند

۲. سرور (ایران) روی پورت‌های محلی (مثلاً 8080) برای کاربران گوش می‌دهد

۳. کاربر در ایران به localhost:8080 متصل می‌شود

۴. ترافیک از طریق WebSocket به کلاینت NL تونل می‌شود

۵. کلاینت NL اتصال واقعی به وب‌سایت‌های مسدود شده برقرار می‌کند

۶. پاسخ از طریق تونل به کاربر برمی‌گردد

CloudFlare/DNS: به IP سرور ایران اشاره می‌کند (جایی که سرور WebSocket برای اتصالات کلاینت گوش می‌دهد)

## نحو نگاشت پورت

سرور تنظیمات نگاشت پورت انعطاف‌پذیر را پشتیبانی می‌کند (سرور گوش می‌دهد، کلاینت متصل می‌شود):

```toml
ports=[
    "443-600",              # گوش دادن روی تمام پورت‌های 443-600، ارسال به همان پورت در ریموت
    "443-600:5201",         # گوش دادن روی تمام پورت‌های 443-600، ارسال همه به پورت ریموت 5201
    "443-600=1.1.1.1:5201", # گوش دادن روی تمام پورت‌های 443-600، ارسال همه به 1.1.1.1:5201
    "443",                   # گوش دادن روی پورت محلی 443، ارسال به پورت ریموت 443
    "4000=5000",             # گوش دادن روی پورت محلی 4000، ارسال به پورت ریموت 5000
    "127.0.0.2:443=5201",    # اتصال به 127.0.0.2:443، ارسال به پورت ریموت 5201
    "443=1.1.1.1:5201",      # گوش دادن روی پورت محلی 443، ارسال به 1.1.1.1:5201
    "127.0.0.2:443=1.1.1.1:5201", # اتصال به 127.0.0.2:443، ارسال به 1.1.1.1:5201
]
```

## تنظیمات

### تنظیمات سرور (/etc/ghostwire/server.toml)

**مکان:** کشور دارای سانسور (ایران) - IP عمومی دارد، برای اتصالات کلاینت گوش می‌دهد

```toml
[server]
protocol="websocket"        # "websocket" (پیش‌فرض)، "http2" یا "grpc"
listen_host="0.0.0.0"
listen_port=8443
listen_backlog=4096         # عمق صف گوش دادن TCP
websocket_path="/ws"        # فقط برای پروتکل websocket استفاده می‌شود
ping_interval=30            # فاصله پینگ سطح برنامه (ثانیه)
ping_timeout=60             # تایم‌اوت اتصال (ثانیه)
ws_pool_enabled=true        # فعال کردن استخر کانال فرزند (پیش‌فرض: true)
ws_pool_children=8          # حداکثر کانال‌های WebSocket موازی
ws_pool_min=2               # حداقل کانال‌های همیشه متصل (پیش‌فرض: 2)
ws_pool_stripe=false        # خط زدن پکت‌ها در کانال‌ها (ناپایدار، پیش‌فرض: false)
udp_enabled=true            # همچنین برای UDP روی پورت‌های تونل گوش می‌دهد (پیش‌فرض: true)
ws_send_batch_bytes=65536   # حداکثر بایت در هر فریم WebSocket (پیش‌فرض: 65536)
auto_update=true
update_check_interval=300
update_check_on_startup=true

[auth]
token="V1StGXR8_Z5jdHi6B-my"

[tunnels]
ports=["8080=80", "8443=443"]

[panel]
enabled=true
host="127.0.0.1"
port=9090
path="aBcDeFgHiJkLmNoPqRsT"
threads=4                  # رشته‌های کارگر سرور HTTP

[logging]
level="info"
file="/var/log/ghostwire-server.log"
```

**پنل مدیریت وب:** سرور شامل یک پنل مدیریت اختیاری مبتنی بر وب برای موارد زیر است:
- پایش بلادرنگ سیستم (CPU، RAM، دیسک، مصرف شبکه)
- تنظیم و مدیریت تونل
- مشاهده لاگ‌ها
- کنترل سرویس (راه‌اندازی مجدد/توقف)
- ویرایش تنظیمات

پنل در `http://127.0.0.1:9090/{path}/` در دسترس است که `path` یک nanoid تصادفی است. دسترسی به‌صورت پیش‌فرض به localhost محدود است. پارامتر `threads` (پیش‌فرض: 4) تعداد رشته‌های کارگر سرور HTTP پنل را کنترل می‌کند.

### تنظیمات کلاینت (/etc/ghostwire/client.toml)

**مکان:** کشور بدون سانسور (هلند) - به سرور متصل می‌شود، درخواست‌های اینترنت را انجام می‌دهد

```toml
[server]
protocol="websocket"        # "websocket" (پیش‌فرض)، "http2" یا "grpc"
url="wss://tunnel.example.com/ws"  # از wss:// برای websocket، https:// برای http2/grpc استفاده کنید
token="V1StGXR8_Z5jdHi6B-my"
ping_interval=30            # فاصله پینگ سطح برنامه (ثانیه)
ping_timeout=60             # تایم‌اوت اتصال (ثانیه)
ws_send_batch_bytes=65536   # حداکثر بایت در هر فریم WebSocket (پیش‌فرض: 65536)
auto_update=true
update_check_interval=300
update_check_on_startup=true

[reconnect]
initial_delay=1
max_delay=60
multiplier=2

[cloudflare]
enabled=false
ips=[]
host=""
check_interval=300
max_connection_time=1740

[logging]
level="info"
file="/var/log/ghostwire-client.log"
```

### تنظیم به‌روزرسانی خودکار

هر دو سرور و کلاینت از به‌روزرسانی خودکار از طریق انتشارهای GitHub پشتیبانی می‌کنند:

- **`auto_update`** (پیش‌فرض: `true`): فعال/غیرفعال کردن به‌روزرسانی خودکار
- **`update_check_interval`** (پیش‌فرض: `300`): ثانیه‌های بین بررسی به‌روزرسانی
- **`update_check_on_startup`** (پیش‌فرض: `true`): بررسی به‌روزرسانی فوری هنگام راه‌اندازی

هنگامی که به‌روزرسانی پیدا شود، فایل باینری دانلود، با چک‌سام SHA-256 تأیید، و سرویس به‌صورت خودکار از طریق systemd راه‌اندازی مجدد می‌شود.

**پروکسی HTTP/HTTPS برای به‌روزرسانی‌ها:** اگر سرور یا کلاینت شما برای دسترسی به GitHub جهت به‌روزرسانی خودکار نیاز به پروکسی دارد، این گزینه‌ها را به بخش `[server]` اضافه کنید:

```toml
update_http_proxy="http://127.0.0.1:8080"
update_https_proxy="http://127.0.0.1:8080"
```

این تنظیمات پروکسی **فقط بر دانلودهای به‌روزرسانی خودکار** از GitHub تأثیر می‌گذارند و بر ترافیک تونل تأثیر نمی‌گذارند. اگر پروکسی نیاز نیست، خالی بگذارید یا حذف کنید.

### تنظیم عملکرد برای همروندی بالا

- **`ws_pool_enabled`** (فقط سرور، پیش‌فرض: true): فعال‌سازی استخر چند اتصاله برای کاهش مشکل TCP-over-TCP تحت بار سنگین

- **`ws_pool_children`** (فقط سرور، پیش‌فرض: 8): حداکثر اتصالات WebSocket موازی
  - **2-4**: استفاده سبک (کمتر از ۵۰ اتصال همزمان)
  - **8**: پیش‌فرض، مناسب برای بیشتر استقرارها
  - **16-32**: استفاده سنگین (چندین کاربر همزمان)

- **`ws_pool_min`** (فقط سرور، پیش‌فرض: 2): حداقل کانال‌های همیشه متصل؛ استخر بر اساس بار بین حداقل و حداکثر مقیاس می‌شود

- **`ws_pool_stripe`** (فقط سرور، پیش‌فرض: false): توزیع پکت‌ها روی کانال‌ها — به دلیل ناپایداری زیر ضعف سیگنال غیرفعال است

- **`udp_enabled`** (فقط سرور، پیش‌فرض: true): گوش دادن UDP روی پورت‌های تونل

- **`ws_send_batch_bytes`** (هر دو، پیش‌فرض: 65536): حداکثر بایت در هر فریم WebSocket
  - مقادیر پایین‌تر تأخیر را زیر بار سنگین (speedtest، ویدیو) کاهش می‌دهند
  - **65536 (64KB)**: پیش‌فرض، بهترین تعادل برای بیشتر موارد
  - **262144 (256KB)**: توان عملیاتی بالاتر، افزایش تأخیر زیر بار
  - **16384 (16KB)**: کمترین تأخیر، کمی کاهش توان عملیاتی

- **`ping_interval`** و **`ping_timeout`**: برای پایداری CloudFlare حیاتی است (هم روی سرور و هم کلاینت تنظیم کنید)
  - **برای تأخیر کم (< 50ms)**: `ping_interval=10`، `ping_timeout=10`
  - **برای تأخیر زیاد (> 200ms، CloudFlare)**: `ping_interval=30`، `ping_timeout=60`
  - تایم‌اوت‌های تهاجمی (< 15 ثانیه) باعث اتصال مجدد مداوم روی لینک‌های WAN با تأخیر زیاد می‌شوند
  - CloudFlare تأخیر 5-500ms اضافه می‌کند و تایم‌اوت بیکاری 100 ثانیه دارد، بنابراین فاصله پینگ 30 ثانیه توصیه می‌شود

## گزینه‌های پروتکل

گوست‌وایر از سه پروتکل انتقال پشتیبانی می‌کند، هر کدام با معاملات متفاوت:

### پروتکل WebSocket (protocol="websocket") - پیش‌فرض

بهترین برای: CloudFlare، استفاده عمومی، حداکثر سازگاری

- ✅ با CloudFlare کار می‌کند (نیاز به فعال بودن WebSockets دارد)

- ✅ ابزارهای اشکال‌زدایی مبتنی بر مرورگر ساده در دسترس است

- ✅ به طور گسترده‌ای توسط پروکسی‌ها و لود بالانسرها پشتیبانی می‌شود

- ❌ پروکسی‌های فقط HTTP/2 ممکن است ارتقا WebSocket را مسدود کنند (باعث HTTP 426 می‌شود)

- ❌ نیاز به مدیریت هدر Upgrade ویژه در nginx دارد

**تنظیمات:**
```toml
[server]
protocol="websocket"
url="wss://tunnel.example.com/ws"
```

### پروتکل HTTP/2 (protocol="http2") - اتصال مستقیم

بهترین برای: اتصالات مستقیم بدون CloudFlare، راه‌اندازی پروکسی سفارشی

- ✅ جریان‌های بومی HTTP/2 (بدون دستکش WebSocket)

- ✅ ابزارهای اشکال‌زدایی پروتکل ساده در دسترس است

- ✅ بدون سربار protobuf

- ❌ **سازگار با CloudFlare نیست** (جریان‌های خام HTTP/2 پشتیبانی نمی‌شوند)

- ❌ نیاز به پروکسی یا اتصال مستقیم HTTP/2 دارد

**تنظیمات:**
```toml
[server]
protocol="http2"
url="https://tunnel.example.com/tunnel"
```

**تنظیمات nginx:**
```nginx
location /tunnel {
    proxy_pass http://127.0.0.1:8443;
    proxy_http_version 1.1;
    proxy_buffering off;
    proxy_read_timeout 86400s;
}
```

### پروتکل gRPC (protocol="grpc") - بهینه‌سازی شده برای CloudFlare

بهترین برای: CloudFlare با gRPC فعال، سناریوهای عملکرد بالا

- ✅ سازگار با CloudFlare (نیاز به Network → gRPC فعال دارد)

- ✅ بالاترین کارایی توان عملیاتی (سریال‌سازی protobuf)

- ✅ مولتیپلکسینگ جریان داخلی

- ✅ کمترین سربار پروتکل

- ❌ نیاز به تغییر gRPC CloudFlare یا پروکسی آگاه از gRPC دارد

- ❌ اشکال‌زدایی پیچیده‌تر

**تنظیمات:**
```toml
[server]
protocol="grpc"
url="https://tunnel.example.com/tunnel"
```

**تنظیمات nginx برای CloudFlare:**
```nginx
location /tunnel {
    grpc_pass grpc://127.0.0.1:8443;
    grpc_set_header Host $host;
    grpc_read_timeout 86400s;
    grpc_send_timeout 86400s;
}
```

**راهنمای انتخاب پروتکل:**
- **از WebSocket استفاده کنید** اگر: از طریق CloudFlare اجرا می‌کنید (رایج‌ترین حالت)، حداکثر سازگاری نیاز دارید
- **از gRPC استفاده کنید** اگر: از طریق CloudFlare با gRPC فعال اجرا می‌کنید، بهترین عملکرد می‌خواهید
- **از HTTP/2 استفاده کنید** اگر: اتصال مستقیم بدون CloudFlare، راه‌اندازی پروکسی سفارشی

## پیکربندی پروکسی

### nginx (راه‌اندازی دستی)

**برای پروتکل WebSocket:**
```nginx
location /ws {
    proxy_pass http://127.0.0.1:8443;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_read_timeout 86400;
    proxy_send_timeout 86400;
    proxy_buffering off;
    proxy_request_buffering off;
    tcp_nodelay on;
}
```

**برای پروتکل HTTP/2:**
```nginx
location /tunnel {
    proxy_pass http://127.0.0.1:8443;
    proxy_http_version 1.1;
    proxy_buffering off;
    proxy_read_timeout 86400s;
}
```

**برای پروتکل gRPC:**
```nginx
location /tunnel {
    grpc_pass grpc://127.0.0.1:8443;
    grpc_set_header Host $host;
    grpc_set_header X-Real-IP $remote_addr;
    grpc_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    grpc_read_timeout 86400s;
    grpc_send_timeout 86400s;
}
```

**برای gRPC با CloudFlare:**
```nginx
server {
    listen 443 ssl http2;
    server_name tunnel.example.com;

    ssl_certificate /etc/letsencrypt/live/tunnel.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/tunnel.example.com/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    location /tunnel {
        grpc_pass grpc://127.0.0.1:8443;
        grpc_set_header Host $host;
        grpc_set_header X-Real-IP $remote_addr;
        grpc_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        grpc_read_timeout 86400s;
        grpc_send_timeout 86400s;
    }
}
```

نکات مهم برای gRPC با nginx:
- nginx نسخه 1.13.10+ برای پشتیبانی از gRPC لازم است
- از `grpc_pass` به جای `proxy_pass` استفاده کنید
- از دستورات تایم‌اوت `grpc_*` به جای `proxy_*` استفاده کنید
- CloudFlare نیاز به فعال بودن تغییر **Network → gRPC** دارد
- مسیر URL برای gRPC `/tunnel` است (نه `/ws`)

**نکته:** `proxy_buffering off` و `proxy_request_buffering off` برای WebSocket حیاتی هستند - بدون آن‌ها nginx فریم‌ها را بافر می‌کند و باعث کاهش چشمگیر توان عملیاتی می‌شود.

### nginx Proxy Manager (NPM)

**برای پروتکل WebSocket:**
1. یک Proxy Host جدید به `127.0.0.1:8443` ایجاد کنید
2. تغییر **"Websockets Support"** را در تب Details فعال کنید
3. در تب **Advanced**، این دستورات سفارشی را اضافه کنید:

```nginx
proxy_read_timeout 86400;
proxy_send_timeout 86400;
proxy_buffering off;
proxy_request_buffering off;
tcp_nodelay on;
```

**برای پروتکل HTTP/2 یا gRPC:**
- از همان دستورات تایم‌اوت استفاده کنید
- تغییر "Websockets Support" را فعال **نکنید**
- برای gRPC، NPM باید از پروکسی gRPC پشتیبانی کند (nginx 1.13.10+)

بدون این تایم‌اوت‌ها، NPM اتصال مداوم را بعد از ~60 ثانیه قطع می‌کند.

### CloudFlare

**سازگاری پروتکل با CloudFlare:**

| پروتکل | پشتیبانی CloudFlare | نکات |
|---------|---------------------|------|
| WebSocket | ✅ بله (با تنظیمات) | نیاز به Network → WebSockets ON |
| gRPC | ✅ بله (با تنظیمات) | نیاز به Network → gRPC ON |
| HTTP/2 | ❌ خیر | سازگار نیست - از اتصال مستقیم استفاده کنید |

**تنظیمات ضروری داشبورد CloudFlare**

برای **پروتکل WebSocket**:
1. **Network → WebSockets**: باید فعال باشد (به‌صورت پیش‌فرض خاموش است - باعث قطع اتصال می‌شود!)
2. **SSL/TLS → Overview**: روی **Full (Strict)** تنظیم کنید (نه "Flexible")
3. **Speed → Rocket Loader**: خاموش کنید (اتصالات WebSocket را خراب می‌کند)
4. **Speed → Auto Minify**: همه را غیرفعال کنید (HTML، CSS، JS)
5. **Speed → Early Hints**: خاموش کنید

برای **پروتکل gRPC**:
1. **Network → gRPC**: باید فعال باشد (به‌صورت پیش‌فرض خاموش است)
2. **SSL/TLS → Overview**: روی **Full (Strict)** تنظیم کنید (نه "Flexible")
3. **Speed → Rocket Loader**: خاموش کنید
4. **Speed → Auto Minify**: همه را غیرفعال کنید (HTML، CSS، JS)
5. **Speed → Early Hints**: خاموش کنید

**تنظیمات کلاینت برای CloudFlare:**

سطح رایگان CloudFlare تایم‌اوت بیکاری 100 ثانیه و **محدودیت سخت اتصال 30 دقیقه‌ای** دارد. اتصال مجدد پیشگیرانه را فعال کنید:

```toml
[cloudflare]
enabled=true
max_connection_time=1740  # 29 دقیقه - قبل از محدودیت 30 دقیقه اتصال مجدد برقرار کن
```

با `enabled=true` و `ips`/`host` خالی، انتخاب IP نادیده گرفته می‌شود اما اتصال مجدد پیشگیرانه همچنان اعمال می‌شود.

## دستورات CLI

**بروزرسانی دستی:**
```bash
sudo ghostwire-server update
sudo ghostwire-client update
```
آخرین نسخه را از GitHub بررسی می‌کند، دانلود و تأیید می‌کند، جایگزین فایل فعلی می‌شود و سرویس را به‌صورت خودکار ری‌استارت می‌کند.

**راه‌اندازی پنل:**
```bash
sudo ghostwire-server panel configure
```
ویزارد تعاملی: پنل مدیریت وب را در `server.toml` فعال می‌کند (اگر قبلاً تنظیم نشده باشد) و به صورت اختیاری nginx را با گواهی TLS پیکربندی می‌کند.

**سایر:**
```bash
ghostwire-server --version
ghostwire-server --generate-token
```

## مدیریت systemd

### سرور:

```bash
sudo systemctl start ghostwire-server
sudo systemctl stop ghostwire-server
sudo systemctl restart ghostwire-server
sudo systemctl status ghostwire-server
sudo journalctl -u ghostwire-server -f
```

### کلاینت:

```bash
sudo systemctl start ghostwire-client
sudo systemctl stop ghostwire-client
sudo systemctl restart ghostwire-client
sudo systemctl status ghostwire-client
sudo journalctl -u ghostwire-client -f
```

## ساخت از سورس

```bash
pip install -r requirements.txt
cd build
chmod +x build.sh
./build.sh
```

فایل‌های باینری در پوشه `dist/` ایجاد می‌شوند.

## مجوز

MIT License - جزئیات در فایل LICENSE

## مشارکت

مشارکت‌ها خوش‌آمد هستند! لطفاً یک issue باز کنید یا یک pull request ارسال کنید.

## کانال تلگرام

برای دریافت به‌روزرسانی‌ها و اطلاعیه‌ها به کانال تلگرام بپیوندید: [@GhostSoftDev](https://t.me/GhostSoftDev)

## پشتیبانی

برای مشکلات و سؤالات، لطفاً یک issue در GitHub باز کنید.
