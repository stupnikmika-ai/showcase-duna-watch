"""Logica compartida: config, ventana de fechas, chequeo, avisos, watchdog.

La usan igual el CLI local (watch.py) y la function de Vercel (api/check.py).
"""
import datetime
import json
import os
import urllib.error

from . import notify, showcase
from .store import build_store

# Argentina no tiene horario de verano: offset fijo, sin depender de tzdata
# (las imagenes serverless muchas veces no la traen).
AR_TZ = datetime.timezone(datetime.timedelta(hours=-3), "ART")

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # .../api
ROOT = os.path.dirname(HERE)
# En serverless el disco del proyecto es read-only: solo /tmp se puede escribir
# (y se borra entre invocaciones, por eso ahi hace falta el store de Redis).
SERVERLESS = bool(os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"))
LOCAL_STATE = "/tmp/showcase-duna-state.json" if SERVERLESS else os.path.join(ROOT, "state.json")
LOCAL_LOG = os.path.join(ROOT, "watch.log")
ENV_PATH = os.path.join(ROOT, ".env")

DEFAULT_KEYWORDS = "duna,dune"
DEFAULT_RELEASE = "2026-12-14"
DEFAULT_DAYS_BEFORE = 80
DEFAULT_DAYS_AFTER = 0

BUY_URL = ("https://entradas.todoshowcase.com/showcase/pelicula?filmid=%s&house_id="
           + showcase.TARGET_HOUSE_ID)
CINEMA = showcase.SECTIONS[showcase.TARGET_SECTION]

WATCHDOG_STRIKES = 3
WATCHDOG_COOLDOWN_H = 24


# ------------------------------------------------------------------ config
def load_config():
    cfg = {}
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH) as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip().strip('"').strip("'")
    prefixes = ("ALERT_", "TWILIO_", "TELEGRAM_", "RESEND_", "MAIL_", "MACOS_",
                "CHANNELS", "KEYWORDS", "WATCH_", "RELEASE_", "PRE_WINDOW",
                "KV_", "UPSTASH_", "STATE_KEY", "CRON_SECRET")
    for k, v in os.environ.items():
        if k.startswith(prefixes):
            cfg[k] = v
    return cfg


def now():
    return datetime.datetime.now(AR_TZ)


def stamp():
    return now().strftime("%Y-%m-%d %H:%M:%S %Z")


class Logger:
    """Junta las lineas para poder devolverlas en la respuesta HTTP."""

    def __init__(self, to_file=True):
        self.lines = []
        self.to_file = to_file

    def __call__(self, msg):
        line = "[%s] %s" % (stamp(), msg)
        self.lines.append(line)
        print(line)
        if self.to_file:
            try:
                with open(LOCAL_LOG, "a") as fh:
                    fh.write(line + "\n")
            except OSError:
                pass


LOG_MAX_BYTES = 2 * 1024 * 1024
LOG_KEEP_LINES = 2000


def _rotar_log():
    """A 720 corridas por dia el log crece sin techo: lo recortamos solo."""
    try:
        if os.path.getsize(LOG_PATH) < LOG_MAX_BYTES:
            return
    except OSError:
        return
    with open(LOG_PATH) as fh:
        cola = fh.readlines()[-LOG_KEEP_LINES:]
    tmp = LOG_PATH + ".tmp"
    with open(tmp, "w") as fh:
        fh.writelines(cola)
    os.replace(tmp, LOG_PATH)


def hours_since(iso):
    if not iso:
        return 1e9
    try:
        t = datetime.datetime.fromisoformat(iso)
    except (ValueError, TypeError):
        return 1e9
    if t.tzinfo is None:
        t = t.replace(tzinfo=AR_TZ)
    return (now() - t).total_seconds() / 3600.0


# ------------------------------------------------------- ventana de fechas
def window(cfg):
    """-> (inicio, fin, release) como date."""
    raw = (cfg.get("RELEASE_DATE") or DEFAULT_RELEASE).strip()
    try:
        release = datetime.date(*[int(x) for x in raw.split("-")])
    except (ValueError, TypeError):
        release = datetime.date(*[int(x) for x in DEFAULT_RELEASE.split("-")])
    try:
        before = int(cfg.get("WATCH_DAYS_BEFORE") or DEFAULT_DAYS_BEFORE)
    except ValueError:
        before = DEFAULT_DAYS_BEFORE
    try:
        after = int(cfg.get("WATCH_DAYS_AFTER") or DEFAULT_DAYS_AFTER)
    except ValueError:
        after = DEFAULT_DAYS_AFTER
    return (release - datetime.timedelta(days=before),
            release + datetime.timedelta(days=after),
            release)


def window_status(cfg, today=None):
    """-> dict con si hay que chequear hoy y por que."""
    start, end, release = window(cfg)
    today = today or now().date()
    inside = start <= today <= end
    mode = (cfg.get("PRE_WINDOW_MODE") or "off").strip().lower()
    return {
        "today": today.isoformat(),
        "release": release.isoformat(),
        "start": start.isoformat(),
        "end": end.isoformat(),
        "inside": inside,
        "days_to_start": (start - today).days,
        "days_to_release": (release - today).days,
        "pre_window_mode": mode,
    }


# ------------------------------------------------------------------ mensajes
def film_line(f):
    bits = [f.title]
    if f.anticipada:
        bits.append("[VENTA ANTICIPADA]")
    elif f.tags:
        bits.append("[%s]" % ", ".join(f.tags))
    return " ".join(bits)


def _esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


PRUEBA_TAG = "[PRUEBA]"
PRUEBA_BANNER = ("*** ESTO ES UNA PRUEBA. No apareció ninguna película nueva: "
                 "es una corrida de verificación del sistema. ***")


def build_alert(new, upgraded, all_films, win, test=False):
    hits = new + upgraded
    on_sale = [f for f in hits if f.anticipada]
    # El titulo real va en el asunto: hardcodear "DUNA" hacia que el aviso
    # mintiera si matcheaba otra cosa o si se cambiaban las KEYWORDS.
    names = ", ".join('"%s"' % f.title for f in hits[:2])
    if len(hits) > 2:
        names += " (+%d mas)" % (len(hits) - 2)
    if not names:
        names = "Una pelicula"
    subject = ("%s ya esta EN VENTA en el IMAX de Norcenter" if on_sale
               else "%s aparecio en la cartelera del IMAX de Norcenter") % names
    if test:
        subject = PRUEBA_TAG + " " + subject

    lines = []
    if test:
        lines += [PRUEBA_BANNER, ""]
    lines += ["Complejo: %s (house_id %s)" % (CINEMA, showcase.TARGET_HOUSE_ID),
              "Estreno estimado: %s (faltan %d dias)" % (win["release"], win["days_to_release"]),
              ""]
    for f in new:
        lines.append("NUEVO EN CARTELERA: " + film_line(f))
        if f.filmid:
            lines.append("  Comprar: " + BUY_URL % f.filmid)
    for f in upgraded:
        lines.append("PASO A VENTA ANTICIPADA: " + film_line(f))
        if f.filmid:
            lines.append("  Comprar: " + BUY_URL % f.filmid)
    lines += ["", "Cartelera completa del IMAX ahora (%d):" % len(all_films)]
    lines += ["  - " + film_line(f) for f in all_films]
    lines += ["", "Cartelera: " + showcase.HOME_URL + "#dropdown_films",
              "Chequeado: " + stamp()]
    if test:
        lines += ["", PRUEBA_BANNER]
    text = "\n".join(lines)

    rows = []
    for label, group in (("NUEVO EN CARTELERA", new), ("PASO A VENTA ANTICIPADA", upgraded)):
        for f in group:
            link = ((' &middot; <a href="%s">Comprar entradas</a>' % (BUY_URL % f.filmid))
                    if f.filmid else "")
            rows.append("<li><b>%s:</b> %s%s</li>" % (label, _esc(film_line(f)), link))
    banner_html = ('<p style="background:#fde68a;color:#713f12;padding:10px 12px;'
                   'border-radius:6px;margin:0 0 12px"><b>%s</b></p>' % _esc(PRUEBA_BANNER)
                   ) if test else ""
    html_body = (
        '<div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;font-size:15px;line-height:1.5">'
        '%s<h2 style="margin:0 0 8px">%s</h2>'
        '<p style="margin:0 0 12px;color:#555">%s &middot; house_id %s &middot; estreno %s</p>'
        "<ul>%s</ul>"
        '<p style="margin:16px 0 4px"><b>Cartelera completa del IMAX ahora (%d):</b></p><ul>%s</ul>'
        '<p style="color:#777;font-size:13px">Chequeado %s &middot; <a href="%s">ver cartelera</a></p></div>'
    ) % (banner_html, _esc(subject), _esc(CINEMA), showcase.TARGET_HOUSE_ID, win["release"],
         "".join(rows), len(all_films),
         "".join("<li>%s</li>" % _esc(film_line(f)) for f in all_films),
         _esc(stamp()), showcase.HOME_URL)
    return subject, text, html_body


def do_notify(subject, text, html_body, cfg, dry, log):
    if dry:
        log("DRY-RUN, no mando nada. Asunto: %s" % subject)
        return []
    res = notify.notify_all(subject, text, html_body, cfg)
    if not res:
        log("!! NINGUN CANAL CONFIGURADO. El aviso NO salio. Completar .env / "
            "variables de entorno (ver .env.example).")
    for r in res:
        log("   canal -> %s" % (r,))
    return res


# ------------------------------------------------------------------ chequeo
def _save(store, st, log):
    try:
        store.save(st)
    except Exception as e:  # noqa: BLE001 - perder el state no debe matar el aviso
        log("!! no pude guardar el estado en %s (%s). Riesgo de avisos repetidos."
            % (store.describe(), e))


def maybe_watchdog(st, cfg, dry, log, why):
    """Solo avisa si NO PUEDE VER la cartelera, nunca porque Duna no este.
    Sin esto, el sitio roto se ve igual que 'todavia no hay Duna' y el aviso
    de verdad nunca llegaria. Se apaga con WATCHDOG=off."""
    if (cfg.get("WATCHDOG") or "on").strip().lower() in ("off", "0", "no"):
        log("watchdog apagado (WATCHDOG=off): no aviso que el scraper esta roto")
        return False
    if st.get("fails", 0) < WATCHDOG_STRIKES:
        return False
    if hours_since(st.get("last_watchdog")) < WATCHDOG_COOLDOWN_H:
        return False
    subject = "El vigia de Duna / IMAX Norcenter se rompio"
    text = ("Llevo %d corridas fallidas seguidas.\n\nMotivo: %s\n\n"
            "Mientras esto pase NO voy a poder avisarte si Duna sale a la venta.\n"
            "Revisar: %s\nUltima corrida OK: %s\n"
            % (st["fails"], why, showcase.HOME_URL, st.get("last_ok") or "nunca"))
    do_notify(subject, text, "<pre>%s</pre>" % _esc(text), cfg, dry, log)
    if not dry:
        st["last_watchdog"] = now().isoformat()
    return True


def run_check(cfg, dry=False, simulate=None, ignore_window=False, log=None,
              store=None):
    """Una corrida completa. Devuelve un dict con lo que paso."""
    log = log or Logger()
    store = store or build_store(cfg, LOCAL_STATE)
    out = {"ok": True, "skipped": None, "alerted": False, "matches": [],
           "films": [], "channels": [], "store": store.describe()}

    win = window_status(cfg)
    out["window"] = win

    if not win["inside"] and not ignore_window and not simulate:
        mode = win["pre_window_mode"]
        st = store.load()
        if mode == "daily" and hours_since(st.get("last_prewindow_check")) >= 20:
            log("fuera de ventana pero PRE_WINDOW_MODE=daily: chequeo igual (1/dia)")
            st["last_prewindow_check"] = now().isoformat()
            if not dry:
                _save(store, st, log)
        else:
            if win["days_to_start"] > 0:
                why = ("todavia no arranca la ventana: empieza el %s (en %d dias), "
                       "estreno %s" % (win["start"], win["days_to_start"], win["release"]))
            else:
                why = ("la ventana ya cerro el %s (estreno %s). Mover RELEASE_DATE o "
                       "subir WATCH_DAYS_AFTER para seguir mirando."
                       % (win["end"], win["release"]))
            log("sin chequear: " + why)
            out["skipped"] = why
            return out

    st = store.load()
    st["last_run"] = now().isoformat()

    try:
        sections = showcase.scrape_home()
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError) as e:
        st["fails"] = st.get("fails", 0) + 1
        log("error de red (%s). fails=%d" % (e, st["fails"]))
        out["ok"] = False
        out["error"] = str(e)
        maybe_watchdog(st, cfg, dry, log, "no pude bajar %s: %s" % (showcase.HOME_URL, e))
        if not dry:
            _save(store, st, log)
        return out

    films = sections.get(showcase.TARGET_SECTION)
    if not films:
        st["fails"] = st.get("fails", 0) + 1
        why = ("no encontre el div '%s' en la home (rediseno del sitio?)"
               % showcase.TARGET_SECTION) if films is None else \
              "la cartelera del IMAX vino vacia (0 peliculas)"
        log("ANOMALIA: %s. fails=%d" % (why, st["fails"]))
        out["ok"] = False
        out["error"] = why
        maybe_watchdog(st, cfg, dry, log, why)
        if not dry:
            _save(store, st, log)
        return out

    st["fails"] = 0
    st["last_ok"] = now().isoformat()

    if simulate:
        fake = showcase.Film("9999", simulate, ["ANTICIPADA IMAX"], "",
                             showcase.TARGET_HOUSE_ID)
        films = list(films) + [fake]
        log("SIMULACION: inyecto %r en la cartelera IMAX" % fake.title)

    keywords = [k.strip() for k in (cfg.get("KEYWORDS") or DEFAULT_KEYWORDS).split(",")]
    hits = showcase.match_films(films, showcase.build_patterns(keywords))
    out["films"] = [f.as_dict() for f in films]
    out["matches"] = [f.as_dict() for f in hits]

    log("IMAX Norcenter: %d peliculas | keywords=%s | matches=%d | %s"
        % (len(films), ",".join(keywords), len(hits), store.describe()))

    new, upgraded = [], []
    for f in hits:
        prev = st["alerted"].get(f.key)
        if prev is None:
            new.append(f)
        elif f.anticipada and not prev.get("anticipada"):
            upgraded.append(f)

    if not (new or upgraded):
        if hits:
            log("match ya avisado, no repito: %s" % ", ".join(f.title for f in hits))
        else:
            log("todavia no hay Duna. Cartelera: %s" % "; ".join(f.title for f in films))
        if not dry:
            _save(store, st, log)
        return out

    subject, text, html_body = build_alert(new, upgraded, films, win, test=bool(simulate))
    log("!! MATCH: %s" % ", ".join(f.title for f in new + upgraded))
    res = do_notify(subject, text, html_body, cfg, dry, log)
    out["alerted"] = True
    out["subject"] = subject
    out["text"] = text
    out["channels"] = [str(r[0]) for r in res]

    if not dry and not simulate:
        for f in new + upgraded:
            st["alerted"][f.key] = {
                "title": f.title, "tags": f.tags, "anticipada": f.anticipada,
                "notified_at": now().isoformat(),
            }
    if not dry:
        _save(store, st, log)
    return out
