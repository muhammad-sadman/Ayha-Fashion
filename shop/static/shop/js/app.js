/* Ayha BD storefront. Everything shown here comes from the Django backend:
   catalog and settings from /api/store/, promo codes from /api/promo/, orders to /api/orders/.
   Prices are always recalculated on the server, so nothing here can change what a customer pays. */
(function () {
  var CONFIG = {}, CATS = [], P = [], PID = {}, BKASH = {}, SHIP = {}, SLIDES = [];
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var cart = [], favs = {}, view = "home", current = null, discount = 0, promoCode = "", ordered = null, sending = false;
  var STORE_KEY = "ayha_state_v2";

  /* ---------- helpers ---------- */
  function tk(n) { return "৳" + Number(n).toLocaleString("en-US"); }
  function esc(t) { return String(t == null ? "" : t).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function toast(m) { var t = $("#toast"); t.textContent = m; t.classList.add("on"); clearTimeout(toast.t); toast.t = setTimeout(function () { t.classList.remove("on"); }, 2400); }
  function normPhone(v) { return String(v || "").replace(/[\s-]/g, "").replace(/^\+?88/, ""); }
  var PHONE_RE = /^01[3-9]\d{8}$/;
  function ph(h, label) { return '<div class="ph" style="background:linear-gradient(160deg,hsl(' + h + ' 42% 32%),hsl(' + ((h + 14) % 360) + ' 48% 18%))"><span>' + esc(label || "Photo") + "</span></div>"; }
  function img(src, alt) { return '<img class="pimg" src="' + esc(src) + '" alt="' + esc(alt || "") + '" loading="lazy" decoding="async">'; }
  function pic(p, label, i) { var s = (p.images || [])[i || 0]; return s ? img(s, p.name) : ph(p.hue, label); }
  function uid() { try { return crypto.randomUUID(); } catch (e) { return "r" + Date.now().toString(36) + Math.random().toString(36).slice(2, 12); } }
  function csrf() { var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/); return m ? decodeURIComponent(m[1]) : ""; }
  var heart = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 21s-8-5.3-8-11a4.5 4.5 0 0 1 8-2.8A4.5 4.5 0 0 1 20 10c0 5.7-8 11-8 11z"/></svg>';
  var arrow = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 12h14m-6-6 6 6-6 6"/></svg>';
  function bkashOn() { return !!(BKASH && BKASH.number); }

  function api(method, url, body) {
    var opts = { method: method, credentials: "same-origin", headers: { Accept: "application/json" } };
    if (body !== undefined) { opts.headers["Content-Type"] = "application/json"; opts.headers["X-CSRFToken"] = csrf(); opts.body = JSON.stringify(body); }
    return fetch(url, opts).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (data) { return { status: r.status, data: data }; });
    });
  }

  function saveState() { try { localStorage.setItem(STORE_KEY, JSON.stringify({ cart: cart, favs: favs })); } catch (e) {} }
  function loadState() {
    try {
      var s = JSON.parse(localStorage.getItem(STORE_KEY) || "null");
      if (s) {
        cart = (s.cart || []).filter(function (l) { return PID[l.id] && PID[l.id].inStock && l.q > 0; });
        favs = s.favs || {};
      }
    } catch (e) {}
  }

  /* ---------- views ---------- */
  function card(p) {
    var off = p.old ? p.old - p.price : 0;
    var tag = !p.inStock ? '<span class="tag soldout">Sold out</span>' : (off ? '<span class="tag">৳' + off + " OFF</span>" : "");
    return '<article class="card' + (p.inStock ? "" : " is-sold") + '">' + tag +
      '<button class="img" data-open="' + p.id + '" aria-label="View ' + esc(p.name) + '">' + pic(p) + "</button>" +
      '<button class="fav" data-fav="' + p.id + '" aria-pressed="' + !!favs[p.id] + '" aria-label="Add to wishlist">' + heart + "</button>" +
      '<div class="body"><button class="name" data-open="' + p.id + '">' + esc(p.name) + "</button>" +
      '<div class="price num">' + tk(p.price) + (p.old ? "<s>" + tk(p.old) + "</s>" : "") + "</div>" +
      (p.inStock ? '<button class="buy" data-buy="' + p.id + '">Buy Now</button>' : '<button class="buy" disabled>Sold out</button>') + "</div></article>";
  }
  function section(c, list) {
    if (!list.length) return "";
    return '<section class="sec" style="padding-block:18px"><div class="shead"><h2>' + esc(c.name) + '</h2><button class="seeall" data-cat="' + esc(c.id) + '">See all</button></div><div class="grid">' + list.slice(0, 8).map(card).join("") + "</div></section>";
  }
  function hero() {
    if (!SLIDES.length) return "";
    var s = SLIDES.map(function (x, i) {
      var art = x.img ? '<div class="art">' + img(x.img, x.h) + "</div>" :
        '<div class="art"><div class="ph" style="background:radial-gradient(circle at 60% 40%,hsl(42 70% 55% / .5),transparent 62%)"><span>Banner photo</span></div></div>';
      return '<div class="slide' + (i ? "" : " on") + '" style="background:linear-gradient(110deg,hsl(' + x.hue + " 55% 13%),hsl(" + ((x.hue + 10) % 360) + ' 45% 24%))" data-i="' + i + '"><div class="copy">' + (x.eyebrow ? '<span class="eyebrow">' + esc(x.eyebrow) + "</span>" : "") + "<h2>" + esc(x.h) + "</h2>" + (x.p ? "<p>" + esc(x.p) + "</p>" : "") + '<button class="cta-pill" data-go="shop">' + esc(x.cta) + " " + arrow + "</button></div>" + art + "</div>";
    }).join("");
    var tr = [["Premium quality", "Fabrics checked"], ["Safe & fast", "Delivery"], ["Trusted by", "your neighbours"], ["Thousands of", "happy customers"]].map(function (t) {
      return '<div><svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><circle cx="12" cy="12" r="10"/><path d="m8 12 3 3 5-6"/></svg><span>' + esc(t[0]) + "<br>" + esc(t[1]) + "</span></div>";
    }).join("");
    var dots = SLIDES.length > 1 ? '<div class="dots">' + SLIDES.map(function (_, i) { return '<button data-dot="' + i + '" aria-label="Slide ' + (i + 1) + '" aria-current="' + (i === 0) + '"></button>'; }).join("") + "</div>" : "";
    return '<div class="wrap"><section class="hero" id="hero" aria-roledescription="carousel">' + s + '<div class="trust">' + tr + "</div>" + dots + "</section></div>";
  }
  function home() {
    var tiles = CATS.map(function (c) { return '<button class="tile" data-cat="' + esc(c.id) + '">' + (c.img ? img(c.img, c.name) : ph(c.hue, "Category photo")) + '<div class="t"><h3>' + esc(c.name) + '</h3><span class="shop">Shop Now ' + arrow + "</span></div></button>"; }).join("");
    var secs = CATS.map(function (c) { return section(c, P.filter(function (p) { return p.cat === c.id; })); }).join("");
    if (!P.length) secs = '<p class="empty">Products are coming soon.</p>';
    return hero() + '<div class="wrap">' + (CATS.length ? '<section class="sec"><div class="tiles">' + tiles + "</div></section>" : "") + secs + "</div>";
  }
  function shop(cat, q) {
    var list = P.filter(function (p) { return (!cat || p.cat === cat) && (!render.sub || p.sub === render.sub) && (!q || p.name.toLowerCase().indexOf(q.toLowerCase()) > -1); });
    var cobj = CATS.filter(function (c) { return c.id === cat; })[0];
    var title = q ? 'Results for "' + esc(q) + '"' : (cobj ? esc(cobj.name) : "All Products");
    return '<div class="wrap"><section class="sec"><div class="shead"><h2>' + title + '</h2><span class="note num">' + list.length + " items</span></div>" +
      (list.length ? '<div class="grid">' + list.map(card).join("") + "</div>" : '<div class="empty">Nothing matched. Try another word.</div>') + "</section></div>";
  }
  function waLink(text) { return CONFIG.whatsappNumber ? "https://wa.me/" + CONFIG.whatsappNumber + "?text=" + encodeURIComponent(text) : ""; }
  function pdp(p) {
    var off = p.old ? p.old - p.price : 0, cobj = CATS.filter(function (c) { return c.id === p.cat; })[0], cn = cobj ? cobj.name : "";
    var n = (p.images || []).length, th = "";
    if (n > 1) { for (var i = 0; i < n; i++) th += '<button data-th="' + i + '" aria-label="Photo ' + (i + 1) + '">' + pic(p, "", i) + "</button>"; }
    else if (!n) { for (var j = 0; j < 4; j++) th += "<button disabled>" + ph((p.hue + j * 10) % 360, "") + "</button>"; }
    var rel = P.filter(function (x) { return x.cat === p.cat && x.id !== p.id; }).concat(P.filter(function (x) { return x.cat !== p.cat; })).slice(0, 4);
    var wa = waLink("Hi, I have a question about: " + p.name);
    var contact = (wa ? '<a href="' + esc(wa) + '" target="_blank" rel="noopener" style="background:#25a85a">WhatsApp</a>' : "") +
      (CONFIG.contact.messenger ? '<a href="' + esc(CONFIG.contact.messenger) + '" target="_blank" rel="noopener" style="background:#1877f2">Messenger</a>' : "");
    var buy = p.inStock ?
      '<div class="btnrow"><button class="btn a" id="addCart">Add to Cart</button><button class="btn b" id="buyNow">Buy Now</button></div>' :
      '<div class="btnrow"><button class="btn a" disabled style="grid-column:1/-1;opacity:.6">Sold out</button></div>';
    return '<div class="wrap"><div class="pdp"><div><div class="photo" id="mainPhoto">' + pic(p, "Product photo") + '</div><div class="thumbs">' + th + "</div></div>" +
      '<div>' + (cn ? '<span class="chip">' + esc(cn) + "</span>" : "") + "<h1>" + esc(p.name) + '</h1><div class="prow num"><span class="big">' + tk(p.price) + "</span>" + (p.old ? "<s>" + tk(p.old) + '</s><span class="off">৳' + off + " OFF</span>" : "") + '<span style="border-left:1px solid var(--line);padding-left:12px;font-size:14px">Availability: <b style="font-weight:500">' + (p.inStock ? "In Stock" : "Sold out") + "</b></span></div>" +
      '<div style="display:flex;justify-content:space-between;align-items:center;border-top:1px solid var(--line);padding-top:14px"><div class="qty"><button id="pm" aria-label="Less">−</button><span id="pq" class="num">1</span><button id="pp" aria-label="More">+</button></div><button class="ibtn" data-fav="' + p.id + '" aria-pressed="' + !!favs[p.id] + '" aria-label="Wishlist" style="color:var(--fg)">' + heart.replace(/15/g, "24") + "</button></div>" +
      buy + (contact ? '<div class="box contact"><h3>Contact Us</h3>' + contact + "</div>" : "") +
      '<div class="box" style="font-size:14px;line-height:1.7">' + esc(SHIP.dhaka.label) + " within " + esc(SHIP.dhaka.days) + ' days: <b class="num">' + tk(SHIP.dhaka.fee) + "</b><br>" + esc(SHIP.out.label) + " within " + esc(SHIP.out.days) + ' days: <b class="num">' + tk(SHIP.out.fee) + "</b></div></div></div>" +
      '<div class="tabs" role="tablist"><button role="tab" aria-selected="true" id="tDesc">Description</button><button role="tab" aria-selected="false" id="tRev">Review</button></div>' +
      '<div id="tabBody"><div class="spec">' + (p.spec.length ? p.spec.map(esc).join("<br>") : "Details coming soon.") + "</div></div>" +
      '<section class="sec"><div class="shead"><h2>Related <em>Products</em></h2><button class="seeall" data-go="shop">See all</button></div><div class="grid">' + rel.map(card).join("") + "</div></section></div>";
  }

  /* ---------- cart + checkout ---------- */
  function totals() {
    var sub = 0;
    cart.forEach(function (l) { sub += PID[l.id].price * l.q; });
    var area = ($("input[name=area]:checked") || {}).value || "out";
    var ship = cart.length ? SHIP[area].fee : 0;
    var d = Math.min(discount, sub);
    return { sub: sub, ship: ship, disc: d, area: area, total: sub + ship - d };
  }
  function sumHtml() {
    var t = totals();
    return '<div class="sumrow num"><span>Subtotal</span><span>' + tk(t.sub) + '</span></div><div class="sumrow ship num"><span>Shipping Charge</span><span>' + tk(t.ship) + '</span></div><div class="sumrow disc num"><span>Discount</span><span>' + tk(t.disc) + '</span></div><div class="sumrow tot num"><span>Total</span><span>' + tk(t.total) + "</span></div>";
  }
  function bkPanel() {
    if (!bkashOn()) return "";
    return '<div class="panel bkbox" id="bk" hidden><h3><span class="bkmark">bKash</span>Pay with bKash</h3>' +
      '<ol><li>Open your bKash app and choose <b>' + (BKASH.type === "Merchant" ? "Payment" : "Send Money") + '</b>.</li><li>Send exactly <span class="bkamt num" id="bkAmt"></span> to this ' + esc(String(BKASH.type).toLowerCase()) + " number:</li><li>Copy the Transaction ID (TrxID) from your bKash receipt and enter it below.</li></ol>" +
      '<div class="bknum"><b class="num" id="bkNum">' + esc(BKASH.number) + '</b><button type="button" id="cpBk">Copy number</button></div>' +
      '<div class="two" style="margin-top:12px"><div class="f"><label for="bn">Your bKash number *</label><input id="bn" type="tel" inputmode="tel" placeholder="01XXXXXXXXX" autocomplete="off"></div><div class="f"><label for="bt">Transaction ID (TrxID) *</label><input id="bt" placeholder="e.g. 8N7A6D5E4C" autocomplete="off" style="text-transform:uppercase"></div></div>' +
      '<div class="note">We check every payment against our bKash history, then confirm your order by phone.</div></div>';
  }
  function checkout() {
    if (ordered) {
      var o = ordered;
      var pay = o.payment === "bKash" ? "We will verify your bKash payment (TrxID " + esc(o.trx) + ", " + tk(o.total) + ") and confirm your order by phone." : "Your order total is " + tk(o.total) + ". Pay when it arrives.";
      var wa = o.whatsapp_url ? '<a class="btn wa" href="' + esc(o.whatsapp_url) + '" target="_blank" rel="noopener">Send order on WhatsApp</a><p class="note">' + (CONFIG.whatsappAutoOpen ? "Opening WhatsApp in a moment. Tap Send there so we can confirm faster." : "Tap the button and press Send so we can confirm faster.") + "</p>" : "";
      return '<div class="wrap"><div class="done"><h2>Thank you, ' + esc(o.name) + '.</h2><p>Your order <b class="num">' + esc(o.no) + "</b> is placed. " + pay + "</p>" + wa +
        '<button class="btn a" data-go="home" style="padding-inline:28px;margin-top:8px">Back to shop</button></div></div>';
    }
    if (!cart.length) return '<div class="wrap"><div class="empty"><h2 style="font-family:var(--f-display);color:var(--fg)">Your cart is empty</h2><p>Add a product and it will show up here.</p><button class="btn a" data-go="shop" style="padding-inline:28px">Start shopping</button></div></div>';
    var lines = cart.map(function (l, i) {
      var p = PID[l.id];
      return '<div class="line"><div class="th">' + pic(p, "") + '</div><div><div class="ln">' + esc(p.name) + '</div><div class="qrow num"><div class="qty"><button data-q="' + i + '" data-d="-1" aria-label="Less">−</button><span>' + l.q + '</span><button data-q="' + i + '" data-d="1" aria-label="More">+</button></div><span>' + tk(p.price) + '</span></div></div><button class="trash" data-rm="' + i + '" aria-label="Remove">✕</button></div>';
    }).join("");
    var promoRow = CONFIG.promosEnabled ?
      '<div class="panel"><h3>Discount</h3><label class="note" for="pc" style="margin:0 0 6px;display:block;letter-spacing:.06em;text-transform:uppercase">Referral or promo code</label><div class="promo"><input id="pc" placeholder="Enter Code" autocomplete="off"><button type="button" id="applyPc">Apply</button></div></div>' : "";
    var bkOpt = bkashOn() ? '<label class="opt"><input type="radio" name="pay" value="bkash"><span><span class="bkmark">bKash</span><b>Pay with bKash</b></span></label>' : "";
    return '<div class="wrap"><form class="co" id="coForm" novalidate><div><div class="panel"><h3>Shipping &amp; Billing</h3>' +
      '<div class="two"><div class="f"><label for="fn">Full Name *</label><input id="fn" required autocomplete="name" maxlength="120"></div><div class="f"><label for="ph">Phone *</label><input id="ph" type="tel" required autocomplete="tel" inputmode="tel" placeholder="01XXXXXXXXX"></div></div>' +
      '<div class="f"><label for="em">Email (optional)</label><input id="em" type="email" autocomplete="email"></div>' +
      '<div class="f"><label for="ad">Full Address *</label><textarea id="ad" required autocomplete="street-address" maxlength="600"></textarea></div>' +
      '<div class="f" style="margin:0"><label for="nt">Note</label><textarea id="nt" maxlength="1000"></textarea></div>' +
      '<div class="hp" aria-hidden="true"><label for="hp">Leave this empty</label><input id="hp" tabindex="-1" autocomplete="off"></div></div>' +
      '<div class="two" style="margin-top:16px"><div class="panel"><h3>Payment Method</h3><label class="opt"><input type="radio" name="pay" value="cod" checked><b>Cash On Delivery</b></label>' + bkOpt + "</div>" +
      '<div class="panel"><h3>Shipping Area</h3><label class="opt"><input type="radio" name="area" value="dhaka"><span><b class="num">' + tk(SHIP.dhaka.fee) + "</b> " + esc(SHIP.dhaka.label) + " " + esc(SHIP.dhaka.days) + '</span></label><label class="opt"><input type="radio" name="area" value="out" checked><span><b class="num">' + tk(SHIP.out.fee) + "</b> " + esc(SHIP.out.label) + " " + esc(SHIP.out.days) + "</span></label></div></div>" + bkPanel() + "</div>" +
      "<div>" + promoRow +
      '<div class="panel" style="margin-top:12px"><h3>Order Summary</h3><div class="lines">' + lines + '</div><div id="sum"></div><button class="place" type="submit" id="placeBtn">Place Order</button><div class="note" id="err" role="alert"></div></div></div></form></div>';
  }
  var FIELDS = ["fn", "ph", "em", "ad", "nt", "bn", "bt", "pc"];
  function saveForm() {
    if (!$("#coForm")) return;
    var f = {};
    FIELDS.forEach(function (k) { var e = $("#" + k); if (e) f[k] = e.value; });
    f.pay = $("input[name=pay]:checked").value; f.area = $("input[name=area]:checked").value;
    saveForm.d = f;
  }
  function restoreForm() {
    var f = saveForm.d;
    if (!f || !$("#coForm")) return;
    FIELDS.forEach(function (k) { var e = $("#" + k); if (e) e.value = f[k] || ""; });
    var a = $("input[name=pay][value=" + f.pay + "]"), b = $("input[name=area][value=" + f.area + "]");
    if (a) a.checked = true; if (b) b.checked = true;
    $("#sum").innerHTML = sumHtml(); updBk();
  }
  function cartChanged() { submitOrder.ref = null; }
  function rerender() { cartChanged(); saveForm(); render(); restoreForm(); }
  function updBk() { var b = $("#bk"); if (!b) return; b.hidden = $("input[name=pay]:checked").value !== "bkash"; $("#bkAmt").textContent = tk(totals().total); }
  function info(t, body) { return '<div class="wrap"><section class="sec" style="max-width:720px"><div class="shead"><h2>' + t + "</h2></div>" + body + "</section></div>"; }

  /* ---------- render + routing ---------- */
  var timer;
  function render() {
    clearInterval(timer);
    var h = "";
    if (view === "home") h = home();
    else if (view === "shop") h = shop(render.cat, render.q);
    else if (view === "pdp") h = pdp(current);
    else if (view === "checkout") h = checkout();
    else if (view === "about") h = info("About Us", "<p>" + esc(CONFIG.about) + "</p>");
    else if (view === "contact") h = info("Contact Us", "<p>" + (CONFIG.contact.phone ? "Phone: " + esc(CONFIG.contact.phone) + "<br>" : "") + (CONFIG.contact.email ? "Email: " + esc(CONFIG.contact.email) + "<br>" : "") + (CONFIG.contact.address ? "Address: " + esc(CONFIG.contact.address) : "") + "</p>");
    $("#view").innerHTML = h;
    ["Home", "Shop", "About", "Contact"].forEach(function (n) {
      var b = $("#n" + n); b.removeAttribute("aria-current");
      if ((view === "home" && n === "Home") || ((view === "shop" || view === "pdp") && n === "Shop") || (view === "about" && n === "About") || (view === "contact" && n === "Contact")) b.setAttribute("aria-current", "page");
    });
    var s = $("#sum"); if (s) s.innerHTML = sumHtml();
    if (view === "home" && SLIDES.length > 1 && !matchMedia("(prefers-reduced-motion:reduce)").matches) timer = setInterval(function () { go2((cur() + 1) % SLIDES.length); }, 5500);
    bar(); badges();
    document.title = (view === "pdp" && current ? current.name + " | " : "") + (CONFIG.brand.name || "Ayha") + " BD";
  }
  function bar() {
    var act = (view === "shop" && !render.q && render.cat) || (view === "pdp" && current.cat) || null;
    $("#ctabs").innerHTML = CATS.map(function (c) { return '<button role="tab" data-cat="' + esc(c.id) + '" aria-selected="' + (c.id === act) + '">' + esc(c.name) + "</button>"; }).join("");
    var pe = $("#pills");
    var c = CATS.filter(function (x) { return x.id === render.cat; })[0];
    if (view === "shop" && c && c.subs.length && !render.q) {
      pe.innerHTML = '<button class="pill" data-sub="" aria-pressed="' + !render.sub + '">All ' + esc(c.name.split(" ")[0]) + "</button>" + c.subs.map(function (n) { return '<button class="pill" data-sub="' + esc(n) + '" aria-pressed="' + (render.sub === n) + '">' + esc(n) + "</button>"; }).join("");
      pe.hidden = false;
    } else { pe.innerHTML = ""; pe.hidden = true; }
  }
  function cur() { var a = document.querySelector(".slide.on"); return a ? +a.dataset.i : 0; }
  function go2(i) {
    document.querySelectorAll(".slide").forEach(function (s, k) { s.classList.toggle("on", k === i); });
    document.querySelectorAll("[data-dot]").forEach(function (d, k) { d.setAttribute("aria-current", k === i); });
  }
  function badges() {
    var n = cart.reduce(function (a, l) { return a + l.q; }, 0), c = $("#cartCount"); c.hidden = !n; c.textContent = n;
    var f = Object.keys(favs).filter(function (k) { return favs[k]; }).length, b = $("#favCount"); b.hidden = !f; b.textContent = f;
    saveState();
  }
  function show(v, x) {
    view = v;
    if (v === "shop") { render.cat = (x && x.cat) || null; render.q = (x && x.q) || null; render.sub = null; }
    if (v === "pdp") current = x;
    if (v === "checkout") ordered = null;
    render(); scrollTo(0, 0);
  }
  function toHash(v, x) {
    if (v === "home") return "#/";
    if (v === "shop") return x && x.q ? "#/search/" + encodeURIComponent(x.q) : x && x.cat ? "#/shop/" + x.cat : "#/shop";
    if (v === "pdp") return "#/product/" + x.id;
    return "#/" + v;
  }
  function fromHash() {
    var parts = location.hash.replace(/^#\/?/, "").split("/"), k = parts[0];
    if (k === "shop") return { v: "shop", x: { cat: parts[1] || null } };
    if (k === "search") { var q; try { q = decodeURIComponent(parts.slice(1).join("/")); } catch (e) { q = ""; } return { v: "shop", x: { q: q } }; }
    if (k === "product" && PID[+parts[1]]) return { v: "pdp", x: PID[+parts[1]] };
    if (k === "checkout" || k === "about" || k === "contact") return { v: k };
    return { v: "home" };
  }
  function nav(v, x) {
    var h = toHash(v, x);
    if (location.hash === h || (!location.hash && h === "#/")) show(v, x); else location.hash = h;
  }
  window.addEventListener("hashchange", function () { if (!CONFIG.brand) return; var r = fromHash(); show(r.v, r.x); });
  function addCart(id, q) {
    var p = PID[id]; if (!p || !p.inStock) { toast("Sorry, this item is sold out"); return false; }
    var l = cart.filter(function (l) { return l.id === id; })[0];
    if (l) l.q = Math.min(20, l.q + q); else cart.push({ id: id, q: Math.min(20, q) });
    cartChanged(); badges(); return true;
  }

  /* ---------- placing an order ---------- */
  function itemsText() { return cart.map(function (l) { var p = PID[l.id]; return p.name + " x" + l.q + " (" + tk(p.price * l.q) + ")"; }).join("\n"); }
  function failMsg(er, text) {
    var fb = waLink("Hi, I want to order:\n" + itemsText() + "\nTotal: " + tk(totals().total));
    er.style.color = "var(--bad)";
    er.innerHTML = esc(text) + (fb ? ' You can also <a href="' + esc(fb) + '" target="_blank" rel="noopener" style="text-decoration:underline">order on WhatsApp</a>.' : "");
  }
  function submitOrder() {
    if (sending) return;
    var er = $("#err"), btn = $("#placeBtn");
    var n = $("#fn").value.trim(), p = normPhone($("#ph").value), a = $("#ad").value.trim();
    if (!n || !a || !PHONE_RE.test(p)) { er.style.color = "var(--bad)"; er.textContent = "Add your name, a valid Bangladeshi mobile number and your full address."; return; }
    var pay = $("input[name=pay]:checked").value, bn = normPhone(($("#bn") || {}).value), bt = String(($("#bt") || {}).value || "").trim().toUpperCase();
    if (pay === "bkash" && (!PHONE_RE.test(bn) || !/^[A-Z0-9]{8,12}$/.test(bt))) { er.style.color = "var(--bad)"; er.textContent = "Enter the bKash number you paid from and the TrxID from your receipt (letters and numbers only)."; return; }
    if (!submitOrder.ref) submitOrder.ref = uid();
    var body = {
      client_ref: submitOrder.ref, name: n, phone: p, email: $("#em").value.trim(), address: a, note: $("#nt").value.trim(),
      area: $("input[name=area]:checked").value, payment: pay, bkash_number: pay === "bkash" ? bn : "", trx: pay === "bkash" ? bt : "",
      promo: promoCode, hp: $("#hp").value, items: cart.map(function (l) { return { id: l.id, qty: l.q }; })
    };
    sending = true; btn.disabled = true; btn.textContent = "Placing order..."; er.textContent = "";
    api("POST", "/api/orders/", body).then(function (r) {
      sending = false;
      if (r.data && r.data.ok) {
        var o = r.data.order;
        ordered = o; cart = []; discount = 0; promoCode = ""; submitOrder.ref = null; saveForm.d = null;
        render(); scrollTo(0, 0);
        if (CONFIG.whatsappAutoOpen && o.whatsapp_url) setTimeout(function () { if (ordered === o) location.href = o.whatsapp_url; }, 2200);
        return;
      }
      var b = $("#placeBtn"); if (b) { b.disabled = false; b.textContent = "Place Order"; }
      var e2 = $("#err"); if (!e2) return;
      if (r.status === 403) failMsg(e2, "Your session expired. Please refresh the page and try again.");
      else failMsg(e2, (r.data && r.data.error) || "We could not place your order. Please try again.");
    }).catch(function () {
      sending = false; var b = $("#placeBtn"); if (b) { b.disabled = false; b.textContent = "Place Order"; }
      var e2 = $("#err"); if (e2) failMsg(e2, "We could not reach the shop. Please check your connection and try again.");
    });
  }

  /* ---------- events ---------- */
  $("#searchForm").onsubmit = function (e) { e.preventDefault(); var q = $("#q").value.trim(); nav("shop", q ? { q: q } : null); };
  $("#favBtn").onclick = function () { var n = Object.keys(favs).filter(function (k) { return favs[k]; }).length; toast(n ? n + " item(s) in your wishlist" : "Wishlist is empty"); };

  document.addEventListener("click", function (e) {
    var t = e.target.closest("[data-go],[data-cat],[data-sub],[data-open],[data-buy],[data-fav],[data-dot],[data-q],[data-rm],[data-th]");
    if (!t) return;
    if (t.tagName === "A") e.preventDefault();
    var d = t.dataset;
    if (d.go !== undefined) nav(d.go);
    else if (d.cat !== undefined) nav("shop", { cat: d.cat || null });
    else if (d.sub !== undefined) { render.sub = d.sub || null; render(); }
    else if (d.open) nav("pdp", PID[d.open]);
    else if (d.buy) { if (addCart(+d.buy, 1)) nav("checkout"); }
    else if (d.fav) { var k = +d.fav; favs[k] = !favs[k]; t.setAttribute("aria-pressed", favs[k]); badges(); toast(favs[k] ? "Saved to wishlist" : "Removed from wishlist"); }
    else if (d.dot !== undefined) go2(+d.dot);
    else if (d.th !== undefined) { $("#mainPhoto").innerHTML = pic(current, "Product photo", +d.th); }
    else if (d.q !== undefined) { var l = cart[+d.q]; l.q = Math.max(1, Math.min(20, l.q + +d.d)); rerender(); }
    else if (d.rm !== undefined) { cart.splice(+d.rm, 1); rerender(); }
  });
  document.addEventListener("click", function (e) {
    var id = e.target.id;
    if (id === "pm" || id === "pp") { var s = $("#pq"); s.textContent = Math.max(1, Math.min(20, +s.textContent + (id === "pp" ? 1 : -1))); }
    else if (id === "addCart") { if (addCart(current.id, +$("#pq").textContent)) toast("Added to cart"); }
    else if (id === "buyNow") { if (addCart(current.id, +$("#pq").textContent)) nav("checkout"); }
    else if (id === "tDesc" || id === "tRev") { var r = id === "tRev"; $("#tDesc").setAttribute("aria-selected", !r); $("#tRev").setAttribute("aria-selected", r); $("#tabBody").innerHTML = r ? '<p class="note" style="padding:14px 0">No reviews yet. Be the first to review this product.</p>' : '<div class="spec">' + (current.spec.length ? current.spec.map(esc).join("<br>") : "Details coming soon.") + "</div>"; }
    else if (id === "cpBk") { var num = BKASH.number; try { navigator.clipboard.writeText(num).then(function () { toast("Number copied"); }, function () { toast("Copy failed: " + num); }); } catch (_) { toast(num); } }
    else if (id === "applyPc") {
      var c = $("#pc").value.trim();
      api("POST", "/api/promo/", { code: c }).then(function (r) {
        var ok = r.data && r.data.ok;
        discount = ok ? r.data.amount : 0; promoCode = ok ? r.data.code : "";
        cartChanged(); var sm = $("#sum"); if (sm) { sm.innerHTML = sumHtml(); updBk(); }
        toast(ok ? "Code applied" : (r.data && r.data.error) || "Code not recognised");
      }).catch(function () { toast("Could not check the code. Try again."); });
    }
  });
  document.addEventListener("change", function (e) {
    if (e.target.name === "area") { $("#sum").innerHTML = sumHtml(); updBk(); }
    if (e.target.name === "pay") updBk();
  });
  document.addEventListener("submit", function (e) { if (e.target.id === "coForm") { e.preventDefault(); submitOrder(); } });

  /* ---------- start ---------- */
  function setupChrome() {
    var c = CONFIG.contact, b = CONFIG.brand;
    $("#brandName").textContent = b.name; $("#brandTag").textContent = b.tagline;
    $("#fBrand").textContent = b.name; $("#fTag").textContent = b.tagline; $("#fCopy").textContent = b.name + " BD";
    $("#fText").textContent = CONFIG.footerText;
    $("#fPhone").textContent = c.phone ? "Phone: " + c.phone : ""; $("#fEmail").textContent = c.email ? "Email: " + c.email : ""; $("#fAddr").textContent = c.address;
    document.querySelectorAll("[data-social]").forEach(function (a) { var u = CONFIG.social[a.dataset.social]; if (u) { a.href = u; a.hidden = false; } else a.hidden = true; });
    var chat = $("#chatBtn"), wa = waLink("Hello " + b.name + ", I need some help.");
    if (wa) { chat.href = wa; chat.hidden = false; } else chat.hidden = true;
    $("#year").textContent = new Date().getFullYear();
  }
  function start(data) {
    CONFIG = data.config; CATS = data.categories; P = data.products;
    BKASH = CONFIG.bkash; SHIP = CONFIG.shipping; SLIDES = CONFIG.slides;
    P.forEach(function (p) { PID[p.id] = p; });
    setupChrome(); loadState();
    var r0 = fromHash(); show(r0.v, r0.x);
  }
  function boot() {
    api("GET", "/api/store/").then(function (r) {
      if (r.status !== 200 || !r.data.config) throw new Error("bad");
      start(r.data);
    }).catch(function () {
      $("#view").innerHTML = '<div class="wrap"><div class="empty"><p>We could not load the shop. Please check your connection.</p><button class="btn a" id="retry" style="padding-inline:28px">Try again</button></div></div>';
      var b = $("#retry"); if (b) b.onclick = function () { $("#view").innerHTML = '<div class="wrap"><p class="empty">Loading the shop...</p></div>'; boot(); };
    });
  }
  boot();
})();
