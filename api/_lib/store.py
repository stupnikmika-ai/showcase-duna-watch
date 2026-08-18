"""Persistencia del estado. Local = archivo; serverless = Redis REST.

En serverless no hay disco que sobreviva entre invocaciones, asi que sin un
store externo el aviso se repetiria en cada corrida. UpstashStore habla el REST
de Upstash, que es el mismo que expone Vercel KV (KV_REST_API_URL/TOKEN).
"""
import json
import os
import ssl
import urllib.parse
import urllib.request

EMPTY = {"alerted": {}, "fails": 0, "last_watchdog": None, "last_ok": None,
         "last_run": None, "last_prewindow_check": None}


def _blank():
    return json.loads(json.dumps(EMPTY))


class FileStore:
    """Estado en un archivo JSON al lado del script."""

    def __init__(self, path):
        self.path = path

    def load(self):
        if not os.path.exists(self.path):
            return _blank()
        try:
            with open(self.path) as fh:
                st = json.load(fh)
        except (ValueError, OSError):
            return _blank()
        for k, v in EMPTY.items():
            st.setdefault(k, json.loads(json.dumps(v)))
        return st

    def save(self, st):
        tmp = self.path + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(st, fh, indent=2, ensure_ascii=False)
        os.replace(tmp, self.path)

    def describe(self):
        return "archivo %s" % self.path


class UpstashStore:
    """Estado en una key de Redis via REST (Upstash / Vercel KV)."""

    def __init__(self, url, token, key="showcase-duna-watch:state"):
        self.url = url.rstrip("/")
        self.token = token
        self.key = key

    def _call(self, path):
        req = urllib.request.Request(
            "%s/%s" % (self.url, path),
            headers={"Authorization": "Bearer " + self.token},
        )
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=20, context=ctx) as r:
            return json.loads(r.read().decode("utf-8"))

    def load(self):
        try:
            res = self._call("get/" + urllib.parse.quote(self.key, safe=""))
        except Exception:  # noqa: BLE001 - sin estado preferimos correr que morir
            return _blank()
        raw = res.get("result")
        if not raw:
            return _blank()
        try:
            st = json.loads(raw)
        except ValueError:
            return _blank()
        for k, v in EMPTY.items():
            st.setdefault(k, json.loads(json.dumps(v)))
        return st

    def save(self, st):
        payload = urllib.parse.quote(json.dumps(st, ensure_ascii=False), safe="")
        self._call("set/%s/%s" % (urllib.parse.quote(self.key, safe=""), payload))

    def describe(self):
        return "redis %s" % self.url.split("//")[-1][:40]


def build_store(cfg, local_path):
    """Elige el store segun lo que haya configurado."""
    url = cfg.get("KV_REST_API_URL") or cfg.get("UPSTASH_REDIS_REST_URL")
    tok = cfg.get("KV_REST_API_TOKEN") or cfg.get("UPSTASH_REDIS_REST_TOKEN")
    if url and tok:
        return UpstashStore(url, tok, cfg.get("STATE_KEY") or "showcase-duna-watch:state")
    return FileStore(local_path)
