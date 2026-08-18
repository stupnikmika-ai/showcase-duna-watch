"""Endpoint del cron en Vercel: GET /api/check corre un chequeo.

Protegido con CRON_SECRET: Vercel manda `Authorization: Bearer $CRON_SECRET`
en las invocaciones de cron cuando esa variable existe.
"""
import json
import os
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _lib import core  # noqa: E402
from _lib.store import FileStore, build_store  # noqa: E402


def _authorized(headers):
    secret = os.environ.get("CRON_SECRET")
    if not secret:
        return True, None
    got = headers.get("Authorization") or headers.get("authorization") or ""
    if got == "Bearer " + secret:
        return True, None
    return False, "CRON_SECRET no coincide"


class handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 - lo exige BaseHTTPRequestHandler
        ok, why = _authorized(self.headers)
        if not ok:
            self._send(401, {"ok": False, "error": why})
            return

        qs = self.path.split("?", 1)[1] if "?" in self.path else ""
        params = {k: (v[0] if v else "")
                  for k, v in urllib.parse.parse_qs(qs, keep_blank_values=True).items()}

        cfg = core.load_config()
        log = core.Logger(to_file=False)
        store = build_store(cfg, core.LOCAL_STATE)

        if isinstance(store, FileStore):
            log("!! sin Redis configurado (KV_REST_API_URL/TOKEN o UPSTASH_*): el "
                "estado vive en /tmp y se borra, asi que el aviso puede repetirse "
                "en cada corrida.")

        try:
            res = core.run_check(
                cfg,
                dry="dry" in params,
                simulate=params.get("simulate") or None,
                ignore_window="force" in params,
                log=log,
                store=store,
            )
        except Exception as e:  # noqa: BLE001 - siempre responder algo legible
            self._send(500, {"ok": False, "error": repr(e), "log": log.lines})
            return

        res["log"] = log.lines
        res.pop("films", None)  # el log ya la lista; la respuesta queda corta
        self._send(200 if res.get("ok") else 503, res)

    def _send(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
