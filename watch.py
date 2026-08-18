#!/usr/bin/env python3
"""Vigia la cartelera del IMAX THEATRE (Norcenter) en todoshowcase.com y avisa
cuando aparece una pelicula con "Duna" o "Dune" en el titulo.

    python3 watch.py                  # la corrida del cron
    python3 watch.py --status         # cartelera de hoy + ventana + estado
    python3 watch.py --dry-run        # evalua y muestra el mensaje, sin mandar
    python3 watch.py --test-notify    # mensaje de prueba por los canales activos
    python3 watch.py --simulate       # inyecta una Duna falsa y dispara el aviso real
    python3 watch.py --all-cinemas    # dump de las 8 carteleras (debug)
    python3 watch.py --reset          # olvidar lo ya avisado
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from api._lib import core, showcase  # noqa: E402
from api._lib.store import build_store  # noqa: E402


def cmd_status(cfg):
    win = core.window_status(cfg)
    store = build_store(cfg, core.LOCAL_STATE)
    st = store.load()

    print("\n%s  (house_id %s)  [%s]" % (core.CINEMA, showcase.TARGET_HOUSE_ID, core.stamp()))
    print("estado guardado en: %s" % store.describe())
    print("\nVentana de vigilancia")
    print("  estreno estimado : %s (en %d dias)" % (win["release"], win["days_to_release"]))
    print("  chequea desde    : %s  hasta %s" % (win["start"], win["end"]))
    if win["inside"]:
        print("  ahora            : ACTIVA, chequeando")
    elif win["days_to_start"] > 0:
        print("  ahora            : dormida, arranca en %d dias (pre_window_mode=%s)"
              % (win["days_to_start"], win["pre_window_mode"]))
    else:
        print("  ahora            : cerrada desde %s" % win["end"])

    try:
        sections = showcase.scrape_home()
    except Exception as e:  # noqa: BLE001
        print("\n  no pude bajar la cartelera: %s\n" % e)
        return 1
    films = sections.get(showcase.TARGET_SECTION) or []
    print("\nCartelera IMAX ahora (%d)" % len(films))
    for f in films:
        print("  %-6s %s" % (f.filmid, core.film_line(f)))

    keywords = [k.strip() for k in (cfg.get("KEYWORDS") or core.DEFAULT_KEYWORDS).split(",")]
    hits = showcase.match_films(films, showcase.build_patterns(keywords))
    print("\n  keywords    : %s -> %s"
          % (",".join(keywords), ", ".join(f.title for f in hits) if hits else "sin match"))
    print("  ya avisado  : %s"
          % (", ".join(v["title"] for v in st["alerted"].values()) or "nada"))
    print("  ultimo OK   : %s | fallas seguidas: %s\n"
          % (st.get("last_ok") or "nunca", st.get("fails", 0)))
    return 0


def cmd_all_cinemas():
    sections = showcase.scrape_home()
    for sid, name in showcase.SECTIONS.items():
        films = sections.get(sid)
        if films is None:
            print("\n%-24s %-32s (no encontrada)" % (sid, name))
            continue
        print("\n%-24s %-32s %d peliculas" % (sid, name, len(films)))
        for f in films:
            print("    %-6s %s" % (f.filmid, core.film_line(f)))
    return 0


def cmd_test_notify(cfg, dry):
    log = core.Logger()
    win = core.window_status(cfg)
    subject = "Prueba del vigia Duna / IMAX Norcenter"
    text = ("Esto es una prueba. Si lo estas leyendo, el aviso funciona.\n\n"
            "Cuando 'Duna' o 'Dune' aparezca en la cartelera del %s te llega un "
            "mensaje como este.\n\nVigilo desde el %s hasta el %s (estreno %s), "
            "6 veces por dia.\n%s"
            % (core.CINEMA, win["start"], win["end"], win["release"], core.stamp()))
    res = core.do_notify(subject, text, "<p>%s</p>" % text.replace("\n", "<br>"),
                         cfg, dry, log)
    if res:
        print("\nCanales que respondieron: %s" % ", ".join(str(r[0]) for r in res))
    return 0


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--all-cinemas", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--test-notify", action="store_true")
    ap.add_argument("--simulate", nargs="?", const="Duna: Parte Tres", default=None,
                    metavar="TITULO")
    ap.add_argument("--ignore-window", action="store_true",
                    help="chequear aunque falte para la ventana (para probar)")
    ap.add_argument("--reset", action="store_true")
    args = ap.parse_args()

    cfg = core.load_config()

    if args.reset:
        store = build_store(cfg, core.LOCAL_STATE)
        st = store.load()
        st["alerted"] = {}
        store.save(st)
        print("state de avisos reseteado (%s)" % store.describe())
        return 0
    if args.all_cinemas:
        return cmd_all_cinemas()
    if args.status:
        return cmd_status(cfg)
    if args.test_notify:
        return cmd_test_notify(cfg, args.dry_run)

    res = core.run_check(cfg, dry=args.dry_run, simulate=args.simulate,
                         ignore_window=args.ignore_window)
    if args.dry_run and res.get("text"):
        print("\n----- mensaje que saldria -----\n%s\n-------------------------------\n"
              % res["text"])
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
