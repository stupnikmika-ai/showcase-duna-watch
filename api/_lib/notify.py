"""Canales de aviso. Cada uno se activa solo si tiene sus variables seteadas."""
import base64
import json
import os
import unicodedata
import ssl
import subprocess
import urllib.error
import urllib.parse
import urllib.request


def _post_json(url, payload, headers, timeout=25):
    data = json.dumps(payload).encode("utf-8")
    h = {"Content-Type": "application/json"}
    h.update(headers)
    req = urllib.request.Request(url, data=data, headers=h, method="POST")
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
        return r.status, r.read().decode("utf-8", "replace")


def _post_form(url, fields, headers, timeout=25):
    data = urllib.parse.urlencode(fields).encode("utf-8")
    h = {"Content-Type": "application/x-www-form-urlencoded"}
    h.update(headers)
    req = urllib.request.Request(url, data=data, headers=h, method="POST")
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
        return r.status, r.read().decode("utf-8", "replace")


def _deaccent(s):
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.encode("ascii", "ignore").decode("ascii")


def _split(v):
    return [x.strip() for x in (v or "").replace(";", ",").split(",") if x.strip()]


# --------------------------------------------------------------------------
def send_email_resend(subject, text, html_body, cfg):
    """RESEND_API_KEY + ALERT_EMAILS (coma) + opcional MAIL_FROM."""
    key = cfg.get("RESEND_API_KEY")
    to = _split(cfg.get("ALERT_EMAILS"))
    if not key or not to:
        return None
    payload = {
        "from": cfg.get("MAIL_FROM") or "Showcase Watch <onboarding@resend.dev>",
        "to": to,
        "subject": subject,
        "text": text,
        "html": html_body,
    }
    status, body = _post_json(
        "https://api.resend.com/emails", payload, {"Authorization": "Bearer " + key}
    )
    return ("resend", status, body[:300], to)


def send_telegram(subject, text, cfg):
    """TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_IDS (coma)."""
    token = cfg.get("TELEGRAM_BOT_TOKEN")
    chats = _split(cfg.get("TELEGRAM_CHAT_IDS"))
    if not token or not chats:
        return None
    out = []
    for chat in chats:
        status, body = _post_json(
            "https://api.telegram.org/bot%s/sendMessage" % token,
            {"chat_id": chat, "text": subject + "\n\n" + text, "disable_web_page_preview": False},
            {},
        )
        out.append((chat, status, body[:200]))
    return ("telegram", out)


def send_whatsapp_twilio(subject, text, cfg):
    """TWILIO_ACCOUNT_SID + TWILIO_AUTH_TOKEN + TWILIO_WA_FROM + ALERT_WHATSAPP."""
    sid = cfg.get("TWILIO_ACCOUNT_SID")
    tok = cfg.get("TWILIO_AUTH_TOKEN")
    frm = cfg.get("TWILIO_WA_FROM")
    to_list = _split(cfg.get("ALERT_WHATSAPP"))
    if not (sid and tok and frm and to_list):
        return None
    auth = base64.b64encode(("%s:%s" % (sid, tok)).encode()).decode()
    url = "https://api.twilio.com/2010-04-01/Accounts/%s/Messages.json" % sid
    out = []
    for to in to_list:
        to_n = to if to.startswith("whatsapp:") else "whatsapp:" + to
        frm_n = frm if frm.startswith("whatsapp:") else "whatsapp:" + frm
        try:
            status, body = _post_form(
                url,
                {"From": frm_n, "To": to_n, "Body": subject + "\n\n" + text},
                {"Authorization": "Basic " + auth},
            )
            out.append((to, status, body[:200]))
        except urllib.error.HTTPError as e:
            out.append((to, e.code, e.read().decode("utf-8", "replace")[:200]))
    return ("whatsapp", out)


def send_sms_twilio(subject, text, cfg):
    """TWILIO_ACCOUNT_SID + TWILIO_AUTH_TOKEN + TWILIO_SMS_FROM + ALERT_SMS."""
    sid = cfg.get("TWILIO_ACCOUNT_SID")
    tok = cfg.get("TWILIO_AUTH_TOKEN")
    frm = cfg.get("TWILIO_SMS_FROM")
    to_list = _split(cfg.get("ALERT_SMS"))
    if not (sid and tok and frm and to_list):
        return None
    auth = base64.b64encode(("%s:%s" % (sid, tok)).encode()).decode()
    url = "https://api.twilio.com/2010-04-01/Accounts/%s/Messages.json" % sid
    # Los gateways de SMS en AR rechazan acentos/enie: mandamos ASCII plano.
    body_txt = _deaccent(subject + " " + text)[:1500]
    out = []
    for to in to_list:
        try:
            status, body = _post_form(
                url, {"From": frm, "To": to, "Body": body_txt},
                {"Authorization": "Basic " + auth},
            )
            out.append((to, status, body[:200]))
        except urllib.error.HTTPError as e:
            out.append((to, e.code, e.read().decode("utf-8", "replace")[:200]))
    return ("sms", out)


def send_macos(subject, text, cfg):
    """Notificacion local del Mac. Se puede apagar con MACOS_NOTIFY=0."""
    if cfg.get("MACOS_NOTIFY", "1") == "0":
        return None
    try:
        body = text.split("\n")[0][:180].replace('"', "'")
        title = subject[:80].replace('"', "'")
        subprocess.run(
            ["osascript", "-e",
             'display notification "%s" with title "%s" sound name "Glass"' % (body, title)],
            check=False, timeout=15,
        )
        return ("macos", "ok")
    except Exception as e:  # noqa: BLE001 - un canal roto no debe matar los otros
        return ("macos", "error: %s" % e)


CHANNELS = [
    ("email", lambda s, t, h, c: send_email_resend(s, t, h, c)),
    ("telegram", lambda s, t, h, c: send_telegram(s, t, c)),
    ("whatsapp", lambda s, t, h, c: send_whatsapp_twilio(s, t, c)),
    ("sms", lambda s, t, h, c: send_sms_twilio(s, t, c)),
    ("macos", lambda s, t, h, c: send_macos(s, t, c)),
]


def notify_all(subject, text, html_body, cfg):
    """Manda por todos los canales configurados. Devuelve lista de resultados."""
    results = []
    enabled = (cfg.get("CHANNELS") or "").strip()
    only = {x.strip() for x in enabled.split(",") if x.strip()} if enabled else None
    for name, fn in CHANNELS:
        if only and name not in only:
            continue
        try:
            r = fn(subject, text, html_body, cfg)
            if r is not None:
                results.append(r)
        except urllib.error.HTTPError as e:
            results.append((name, "HTTP %s" % e.code, e.read().decode("utf-8", "replace")[:300]))
        except Exception as e:  # noqa: BLE001
            results.append((name, "error", str(e)[:300]))
    return results
