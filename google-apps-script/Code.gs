/**
 * AYHA BD: ORDER RECEIVER (Google Apps Script), optional
 *
 * The Django shop saves every order in its own database. If you also want each order as a
 * row in a Google Sheet, deploy this script and give its URL to the shop (README, step 6).
 *
 * IMPORTANT: the Django shop already sends your email alert and WhatsApp alert. Leave
 * OWNER_EMAIL below empty and do not set the WA_* Script Properties, or you will get every
 * alert twice.
 *
 * Steps:
 *   1. Create a Google Sheet, then Extensions > Apps Script, and paste this whole file.
 *   2. Run the function  setup  once and approve the permissions.
 *   3. Deploy > New deployment > Web app > Execute as: Me, Who has access: Anyone.
 *   4. Copy the Web app URL into  GOOGLE_SHEET_WEBHOOK_URL  in the shop's .env file.
 */


var SETTINGS = {
  SHEET_NAME: "Orders",
  TIMEZONE: "Asia/Dhaka",
  OWNER_EMAIL: "",            // e.g. "you@gmail.com". Leave "" to skip email alerts.
  STATUS_OPTIONS: ["New", "Confirmed", "Packed", "Shipped", "Delivered", "Cancelled", "Returned"]
};



var HEADERS = [
  "Order No", "Date & Time", "Status", "Name", "Phone", "Email", "Address", "Delivery Area",
  "Items", "Subtotal", "Delivery", "Discount", "Total", "Payment", "bKash Number", "bKash TrxID",
  "Note", "Promo Code"
];

/** Run this ONCE from the editor (Run > setup). Creates the Orders tab with headers. */
function setup() {
  var sh = getSheet_();
  if (sh.getLastRow() === 0) {
    sh.appendRow(HEADERS);
  }
  var head = sh.getRange(1, 1, 1, HEADERS.length);
  head.setFontWeight("bold").setBackground("#10392b").setFontColor("#e8c27a");
  sh.setFrozenRows(1);
  sh.getRange(2, 3, 1000, 1).setDataValidation(
    SpreadsheetApp.newDataValidation().requireValueInList(SETTINGS.STATUS_OPTIONS, true).setAllowInvalid(false).build()
  );
  sh.setColumnWidths(1, HEADERS.length, 130);
  sh.setColumnWidth(7, 280); sh.setColumnWidth(9, 340);
  SpreadsheetApp.flush();
}

/** Open the Web app URL in a browser to check the deployment is live. */
function doGet() {
  return json_({ ok: true, message: "Ayha orders endpoint is live." });
}

function doPost(e) {
  var lock = LockService.getScriptLock();
  try {
    lock.waitLock(20000);
    var o = JSON.parse((e && e.postData && e.postData.contents) || "{}");

    var err = validate_(o);
    if (err) return json_({ ok: false, error: err });

    var sh = getSheet_();
    if (sh.getLastRow() === 0) setup();

    // The same order sent twice (customer retried) is only saved once.
    var dup = sh.getRange(1, 1, Math.max(sh.getLastRow(), 1), 1).createTextFinder(o.no).matchEntireCell(true).findNext();
    if (dup) return json_({ ok: true, duplicate: true });

    var row = [
      o.no,
      Utilities.formatDate(new Date(), SETTINGS.TIMEZONE, "yyyy-MM-dd HH:mm"),
      "New",
      safe_(o.name), o.phone, safe_(o.email), safe_(o.address), safe_(o.area),
      safe_(o.items), num_(o.subtotal), num_(o.shipping), num_(o.discount), num_(o.total),
      o.payment, o.bkashNumber || "", o.trx || "",
      safe_(o.note), safe_(o.promo)
    ];
    var r = sh.getLastRow() + 1;
    [1, 5, 15, 16].forEach(function (c) { sh.getRange(r, c).setNumberFormat("@"); }); // keep leading zeros
    sh.getRange(r, 1, 1, row.length).setValues([row]);
    sh.getRange(r, 7, 1, 3).setWrap(true);

    try { notifyEmail_(o); } catch (x1) { console.error("email failed: " + x1); }
    try { notifyWhatsApp_(o); } catch (x2) { console.error("whatsapp failed: " + x2); }

    return json_({ ok: true });
  } catch (ex) {
    console.error(ex);
    return json_({ ok: false, error: String(ex) });
  } finally {
    try { lock.releaseLock(); } catch (z) {}
  }
}

/* ---------- helpers ---------- */

function getSheet_() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  return ss.getSheetByName(SETTINGS.SHEET_NAME) || ss.insertSheet(SETTINGS.SHEET_NAME);
}

function validate_(o) {
  if (o.hp) return "spam";
  if (!o.no || !/^AY-[0-9]{6}-[A-Z0-9]{4}$/.test(o.no)) return "bad order number";
  if (!o.name || String(o.name).length > 120) return "bad name";
  if (!/^01[3-9][0-9]{8}$/.test(String(o.phone || ""))) return "bad phone";
  if (!o.address || String(o.address).length > 600) return "bad address";
  if (!o.items || String(o.items).length > 3000) return "bad items";
  if (!(Number(o.total) > 0) || Number(o.total) > 1000000) return "bad total";
  if (o.payment !== "Cash on Delivery" && o.payment !== "bKash") return "bad payment";
  if (o.payment === "bKash" && (!/^01[3-9][0-9]{8}$/.test(String(o.bkashNumber || "")) || !/^[A-Z0-9]{8,12}$/.test(String(o.trx || "")))) return "bad bkash details";
  return "";
}

// Stops text like =HYPERLINK(...) from being run as a spreadsheet formula.
function safe_(v) {
  v = String(v == null ? "" : v).substring(0, 3000);
  return /^[=+\-@]/.test(v) ? "'" + v : v;
}
function num_(v) { var n = Number(v); return isFinite(n) ? n : 0; }
function json_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}

function summary_(o) {
  return "Order " + o.no + "\n" +
    "Name: " + o.name + "\nPhone: " + o.phone + "\nAddress: " + o.address + " (" + o.area + ")\n\n" +
    "Items:\n" + o.items + "\n\n" +
    "Subtotal: " + o.subtotal + "  Delivery: " + o.shipping + "  Discount: " + o.discount + "\n" +
    "TOTAL: " + o.total + " BDT\n" +
    "Payment: " + o.payment + (o.payment === "bKash" ? " (from " + o.bkashNumber + ", TrxID " + o.trx + ")" : "") +
    (o.note ? "\nNote: " + o.note : "");
}

function notifyEmail_(o) {
  if (!SETTINGS.OWNER_EMAIL) return;
  MailApp.sendEmail({
    to: SETTINGS.OWNER_EMAIL,
    subject: "New Ayha order " + o.no + " - " + o.total + " BDT (" + o.payment + ")",
    body: summary_(o)
  });
}

/**
 * OPTIONAL: automatic WhatsApp message to YOU through the WhatsApp Cloud API (Meta).
 * Leave the three Script Properties empty to switch this off. The website already opens
 * WhatsApp for the customer, which needs no setup. See README.md, "Automatic WhatsApp".
 *
 * Project Settings > Script Properties:
 *   WA_TOKEN            permanent access token from Meta
 *   WA_PHONE_NUMBER_ID  the Phone number ID of your WhatsApp Business number
 *   WA_OWNER_NUMBER     where to send alerts, digits only, e.g. 8801712345678
 */
function notifyWhatsApp_(o) {
  var p = PropertiesService.getScriptProperties();
  var token = p.getProperty("WA_TOKEN"), id = p.getProperty("WA_PHONE_NUMBER_ID"), to = p.getProperty("WA_OWNER_NUMBER");
  if (!token || !id || !to) return;
  var res = UrlFetchApp.fetch("https://graph.facebook.com/v20.0/" + id + "/messages", {
    method: "post",
    contentType: "application/json",
    headers: { Authorization: "Bearer " + token },
    muteHttpExceptions: true,
    payload: JSON.stringify({ messaging_product: "whatsapp", to: to, type: "text", text: { body: summary_(o) } })
  });
  if (res.getResponseCode() >= 300) console.error("WhatsApp API: " + res.getContentText());
}
