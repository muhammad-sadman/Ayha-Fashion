# Ayha BD: shop website with Django backend

One Django project that serves the green-and-gold storefront **and** the back office. Customers browse, order with Cash on Delivery or manual bKash, and every order is saved in a database. You manage everything from the Django admin: orders, products, photos, prices, banners, promo codes, delivery fees and contact details.

- Customers never see or change prices. The server recalculates every total from the database.
- Each order is saved first, then sent to your email, your Google Sheet (optional) and WhatsApp.
- No customer accounts, no online card/bKash gateway (bKash is manual: customer sends money and enters the TrxID, you verify it).

```
manage.py                  Django command line
ayha_project/              settings, urls, wsgi
shop/models.py             Store settings, categories, products, photos, banners, promo codes, orders
shop/services.py           order pricing, validation, notifications (the important logic)
shop/views.py              the 3 JSON endpoints used by the storefront
shop/admin.py              the admin panel (orders list, slips, CSV, stats)
shop/templates/shop/       index.html (storefront), slip.html (delivery slip)
shop/static/shop/          storefront CSS and JavaScript
shop/tests.py              47 automated tests
google-apps-script/        optional Google Sheet receiver
deploy/                    nginx and systemd examples
.env.example               all settings, copy to .env
```

---

## 1. Run it on your computer (10 minutes)

You need Python 3.10 or newer.

```bash
cd ayha-django
python -m venv venv
source venv/bin/activate            # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env                # Windows: copy .env.example .env
python manage.py migrate
python manage.py createsuperuser    # your admin login (use a long password)
python manage.py seed_demo          # optional: 16 example products and 3 banners
python manage.py runserver
```

Open http://127.0.0.1:8000 for the shop and http://127.0.0.1:8000/admin/ for the admin.

## 2. First setup in the admin

1. **Store settings** (one page): your **WhatsApp number** (digits with 88, like `8801712345678`), **bKash number and type**, delivery fees and days, phone, email, address, Messenger link, Facebook / YouTube / Instagram links, footer and About text.
   - Leave the bKash number empty and the bKash option is hidden from checkout.
   - Leave the WhatsApp number empty and the WhatsApp buttons are hidden.
2. **Categories**: add each category. Its **filter buttons** (like Three Piece, Saree) are added on the same page. Smaller "order" numbers come first. Optional photo for the home tile.
3. **Products**: name, category, price, old price (crossed out, 0 for none), details (one line each), and up to several photos (first photo is the main one). Untick **Is active** to hide, untick **In stock** to show "Sold out". You can edit price, stock and visibility straight from the list.
   - Big phone photos are shrunk automatically when uploaded.
4. **Home banner slides**: the big banner at the top (heading, text, button, optional photo).
5. **Promo codes**: code, taka off, optional expiry and use limit. The promo box only appears at checkout while at least one active code exists.

Delete or edit the demo products from `seed_demo` before you go live.

## 3. Handling orders (admin > Orders)

- The top of the list shows today / last 7 days / this month sales, new orders, and bKash payments waiting for checking (cancelled and returned orders are excluded).
- Open an order or tick several and use the actions: **Mark as Confirmed / Packed / Shipped / Delivered / Cancelled**, **Print delivery slips**, **Export to CSV** (opens in Excel), **Mark bKash payment as verified**.
- **bKash orders:** compare the TrxID and amount with your bKash history, then tick **Payment verified**. The delivery slip says "do not ship until checked" until you do. A TrxID can be used for one order only; reusing it is refused automatically.
- Slips show what to collect from the customer (full total for Cash on Delivery, zero for verified bKash).
- Use the private **admin note** on each order for your own remarks. Customers never see it.

## 4. Where each order goes

When a customer taps Place Order:
1. The order is validated and saved in the database (with a unique order number like `AY-261014-P7DT`).
2. The thank-you page appears and **WhatsApp opens** with the whole order typed out, addressed to your WhatsApp number. The customer must tap **Send**. A website cannot send WhatsApp messages by itself, so some customers may not. The database (and Sheet) always has the order regardless.
3. In the background (checkout never waits for these):
   - **Email** to you if `ORDER_ALERT_EMAIL` (or the field in Store settings) is set and email is configured.
   - **Google Sheet** row if `GOOGLE_SHEET_WEBHOOK_URL` is set.
   - **Automatic WhatsApp message to you** if the WhatsApp Cloud API values (`WA_*`) are set.

If a notification fails (internet problem, Google down) the order is still saved. The admin list has a column showing which orders reached the Sheet. Re-send them from the admin action **Send selected to Google Sheet again**, or run `python manage.py sync_sheet`.

### Email alerts
In `.env` set `ORDER_ALERT_EMAIL`, `EMAIL_HOST_USER` and `EMAIL_HOST_PASSWORD`. For Gmail use an **App password** (Google Account > Security > 2-Step Verification > App passwords), not your normal password.

### Google Sheet (optional)
1. Create a Google Sheet. **Extensions > Apps Script**, paste all of `google-apps-script/Code.gs`.
2. Run the function `setup` once and approve the permissions.
3. **Deploy > New deployment > Web app**, Execute as **Me**, access **Anyone**. Copy the URL ending in `/exec`.
4. Put it in `.env` as `GOOGLE_SHEET_WEBHOOK_URL=...` and restart the server.
5. Leave `OWNER_EMAIL` in Code.gs empty (Django already sends your email), otherwise you get two emails.
6. Keep the sheet private. It holds customers' phone numbers and addresses.

### Automatic WhatsApp to you (optional, advanced)
Uses Meta's WhatsApp Cloud API: create a Meta developer app with WhatsApp, then set `WA_TOKEN`, `WA_PHONE_NUMBER_ID` and `WA_OWNER_NUMBER` in `.env`. Meta only allows free-form messages inside 24 hours of the receiving number messaging your business; outside that window you need an approved message template, which needs a small code change in `send_whatsapp_cloud` (shop/services.py). Failures are logged and never block an order.

## 5. Put it on the internet

The shop needs a host that runs Python. Shared "PHP only" hosting will not work.

### Option A: a Linux VPS (Ubuntu), recommended
```bash
sudo apt update && sudo apt install -y python3-venv nginx certbot python3-certbot-nginx
sudo adduser --system --group --home /srv/ayha ayha
# copy the project folder to /srv/ayha, then as that user:
cd /srv/ayha && python3 -m venv venv && venv/bin/pip install -r requirements.txt
cp .env.example .env && nano .env
```
Edit `.env` for the live site:
```
DJANGO_DEBUG=False
DJANGO_SECRET_KEY=<a long random value>
DJANGO_ALLOWED_HOSTS=ayhabd.com,www.ayhabd.com
DJANGO_CSRF_TRUSTED_ORIGINS=https://ayhabd.com,https://www.ayhabd.com
DJANGO_BEHIND_PROXY=True
DJANGO_ADMIN_URL=pick-a-private-name/
```
Then:
```bash
venv/bin/python manage.py migrate
venv/bin/python manage.py collectstatic --noinput
venv/bin/python manage.py createsuperuser
sudo cp deploy/ayha.service /etc/systemd/system/ && sudo systemctl enable --now ayha
sudo cp deploy/nginx.conf /etc/nginx/sites-available/ayha    # edit paths and domain first
sudo ln -s /etc/nginx/sites-available/ayha /etc/nginx/sites-enabled/ && sudo nginx -t
sudo certbot --nginx -d ayhabd.com -d www.ayhabd.com && sudo systemctl reload nginx
```
Point your domain's DNS **A record** at the server's IP first. Open https://ayhabd.com and log in at your private admin address.

### Option B: cPanel "Setup Python App"
Create a Python app (3.10+), upload the project, set the startup file to `passenger_wsgi.py` and the entry point to `application`, add the `.env` values in the app's environment variables, then run `pip install -r requirements.txt`, `migrate`, `collectstatic` and `createsuperuser` from the app's terminal. Set `DJANGO_SERVE_MEDIA=True`. I could not test cPanel from here, so expect to adjust paths.

### Updating the live site later
Upload the changed files, then `venv/bin/python manage.py migrate`, `collectstatic --noinput` and `sudo systemctl restart ayha`.

## 6. Backups and safety

- **Back up two things regularly:** `db.sqlite3` (all orders and products) and the `media/` folder (photos). Copy them somewhere off the server every day. With SQLite use `sqlite3 db.sqlite3 ".backup backup.db"` for a safe copy.
- Use a **long, unique admin password**, change `DJANGO_ADMIN_URL`, and keep the site on HTTPS. Django has no built-in login lockout, so a hidden admin address and a strong password matter.
- Never share `.env`. Anyone with it can run your shop.
- Customer phone numbers and addresses are personal data. Share the admin only with people you trust, give staff their own accounts (admin > Users) rather than one shared login, and do not leave exported CSV files lying around.
- The order limit is 5 orders per visitor address per 10 minutes by default, and the order form has a hidden field that catches simple bots. A determined person can still place fake orders, so confirm orders by phone before shipping, especially large ones and unverified bKash orders.
- If most visitors come through one shared address (a mobile carrier or office network), raise `ORDER_RATE_LIMIT_COUNT`.

## 7. Tests

```bash
DJANGO_DEBUG=True python manage.py test shop
```
47 tests cover pricing, tampered prices, sold-out items, promo rules, bKash rules and TrxID reuse, retries, spam protection, CSRF, the admin pages, slips, CSV export, notifications and image resizing. Run them after any change.

## 8. Known limits

- Stock is on or off (in stock / sold out). There are no stock counts.
- Everything loads in one catalog request, which is fine for a few hundred products. For thousands, add paging.
- bKash is manual. A real payment gateway needs a bKash merchant account and extra code.
- No customer login, order tracking page or reviews.
- Notifications run in a background thread of the web process. If the server restarts at the exact moment of an order, the email or Sheet row can be missed; the order itself is safe and `sync_sheet` re-sends missed Sheet rows.
- SQLite is fine for a small shop. For heavy traffic switch to PostgreSQL (`DB_ENGINE=postgres` in `.env`).
