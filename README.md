# Vigía Duna — IMAX Norcenter

Chequea la cartelera del **IMAX THEATRE (Norcenter)** en `todoshowcase.com` y avisa
por Telegram (o email / WhatsApp / SMS) cuando aparece una película con **"Duna"**
o **"Dune"** en el título — sin importar mayúsculas ni tildes.

Solo stdlib de Python. No hay `pip install`, no hay navegador, no hay JS.

## Qué mira exactamente

La home de `todoshowcase.com` trae **todas** las carteleras renderizadas del lado
del servidor, una por complejo, en divs escondidos que el `<select>` muestra y
oculta con jQuery. El del IMAX de Norcenter es `cartelera_cine_40219`:

| div | complejo | house_id |
|---|---|---|
| `cartelera_cine_40219` | **IMAX THEATRE (Norcenter)** ← el que vigilamos | 3250 |
| `cartelera_cine_40213` | Showcase Norcenter (salas normales) | 3204 |
| `cartelera_cine_40212` | Showcase Belgrano | 3206 |
| `cartelera_cine_40214` | Showcase Haedo | 3200 |
| `cartelera_cine_40215` | Showcase Quilmes | 3208 |
| `cartelera_cine_40216` | Showcase Córdoba Villa Cabrera | 3202 |
| `cartelera_cine_40217` | Showcase Villa Allende | 3220 |
| `cartelera_cine_40218` | Showcase Rosario | 3210 |

Un solo GET a la home y se parsea ese div. El IMAX de Argentina es uno solo:
Panamericana y Debenedetti, Vicente López — el de Norcenter.

Cada película trae etiqueta: **`ANTICIPADA`** (ya se pueden comprar entradas: esto
es "salió a la venta") o **`IMAX`** (en cartel). El aviso distingue las dos cosas.

## Ventana de vigilancia

No chequea todo el año. Por defecto:

```
estreno            2026-12-14   (RELEASE_DATE)
empieza a chequear 2026-09-25   (80 días antes, WATCH_DAYS_BEFORE)
corta              2026-12-14   (WATCH_DAYS_AFTER=0)
frecuencia         cada 2 min en la Mac (launchd) + ~5/día en GitHub
```

Fuera de esa ventana el script sale sin hacer nada. Si el estreno se corre, mover
`RELEASE_DATE` (o subir `WATCH_DAYS_AFTER`) para que la ventana no cierre antes.

## Cuándo avisa

**Solo cuando aparece.** Si Duna no está, el chequeo no manda nada — ni un "sigo
mirando", ni un resumen diario. Queda una línea en `watch.log` y listo. Los seis
chequeos por día son silenciosos hasta que haya algo.

1. **Duna entra a la cartelera del IMAX** → "apareció en la cartelera".
2. **Ya estaba y pasa a `ANTICIPADA`** → segundo aviso "ya está EN VENTA".
   Esta es la transición que importa.
3. **El scraper no puede LEER la cartelera** → si falla 3 corridas seguidas (el
   sitio cambió, se cayó, cambiaron el id del div) manda un aviso aparte y se
   calla 24 h. Esto no es "Duna no está", es "no puedo ver": sin este aviso un
   rediseño del sitio se vería exactamente igual que "todavía no hay Duna" y el
   aviso de verdad nunca llegaría. Se apaga con `WATCHDOG=off`.

Nunca repite el mismo aviso: lo notificado queda en el estado.

## Configurar

```bash
cp .env.example .env
# completar TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_IDS
python3 watch.py --test-notify
```

**Telegram** (recomendado): `@BotFather` → `/newbot` → copiar el token. Después
cada persona le manda `/start` al bot y los chat ids salen de
`curl "https://api.telegram.org/bot<TOKEN>/getUpdates"`. Van los dos separados
por coma en `TELEGRAM_CHAT_IDS`.

Otros canales en `.env.example`. Se combinan: `CHANNELS=telegram,email`.
El SMS va sin tildes ni ñ automáticamente. WhatsApp por Twilio necesita
plantilla **UTILITY** aprobada para mensajes no solicitados.

## Correr a mano

```bash
python3 watch.py                  # la corrida del cron
python3 watch.py --status         # cartelera de hoy + ventana + estado
python3 watch.py --dry-run        # evalúa y muestra el mensaje, sin mandar
python3 watch.py --simulate       # Duna falsa, dispara el aviso de verdad
python3 watch.py --ignore-window  # chequear aunque falte para la ventana
python3 watch.py --all-cinemas    # dump de las 8 carteleras
python3 watch.py --reset          # olvidar lo ya avisado
```

`--simulate` es la prueba de fuego: recorre el camino completo (parseo → match →
mensaje → envío) con una película falsa y **no** marca nada como avisado, así que
el aviso real sigue intacto.

Todo mensaje de prueba sale marcado: el asunto arranca con **`[PRUEBA]`** y el
cuerpo lleva un cartel arriba y abajo aclarando que no apareció ninguna película.
Un aviso de verdad nunca los tiene, así que no hay forma de confundirlos.

El asunto nombra **la película que realmente matcheó** (`"Duna: Parte Tres" ya
está EN VENTA…`). Antes decía "DUNA" fijo, y si matcheaba otra cosa el mensaje
mentía.

## Dejarlo corriendo

### GitHub Actions (recomendado)

`.github/workflows/watch.yml` ya está listo: cron `23 * * * *`, gratis, sin
límite de plan. Push del repo y después:

- **Secrets** → `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_IDS`
- **Variables** (opcional) → `RELEASE_DATE`, `WATCH_DAYS_BEFORE`, `WATCHDOG`

El estado va en `actions/cache`, que se accede cada hora y no se enfría. Para
probar: *Actions → Vigía Duna → Run workflow* con `force` y/o `simulate`.

**GitHub NO sirve para alta frecuencia.** Tres razones medidas, no teóricas:

1. El intervalo mínimo de `schedule` es **5 minutos**. Un `*/2 * * * *` no se
   honra.
2. Aunque se pida más, GitHub no lo ejecuta. Medido sobre 311 corridas: con
   `0 */4 * * *` (6/día programadas) salían 4; con `23 * * * *` (24/día)
   salen **~5**. Un 79% de descarte.
3. En repo privado cada job factura **1 minuto mínimo** aunque tarde 15 s. A
   2 min serían 21.600 min/mes contra 2.000 gratis: ~USD 157/mes.

Por eso el cron de GitHub se queda en `23 * * * *` como **red de seguridad
siempre encendida** (~5 chequeos/día, ~150 min/mes, gratis), y la alta
frecuencia va en la Mac.

### Vercel

`vercel.json` define el cron `0 */4 * * *` sobre `/api/check`.

```bash
vercel login          # NO usar la cuenta de la cuenta corporativa
vercel link
vercel env add TELEGRAM_BOT_TOKEN
vercel env add TELEGRAM_CHAT_IDS
vercel env add CRON_SECRET
vercel deploy --prod
```

Dos cosas de Vercel:

- **6 chequeos por día necesitan plan Pro.** En Hobby los crons corren 1 vez por
  día y nada más.
- El filesystem es read-only y `/tmp` se borra entre invocaciones, así que hace
  falta un store externo o el aviso se repite cada 4 h. Configurar
  `KV_REST_API_URL` + `KV_REST_API_TOKEN` (Vercel KV o Upstash Redis, free tier
  alcanza). Si falta, `/api/check` lo dice en el log de la respuesta.

Endpoint a mano: `GET /api/check` con `Authorization: Bearer $CRON_SECRET`.
Params: `?force` (ignora la ventana), `?dry` (no manda), `?simulate=Titulo`.

### launchd en la Mac

```bash
./install-cron.sh
```

**Cada 2 minutos**, sobrevive reinicios, y si la Mac estaba dormida arranca al
despertar. Es el único de los dos que alcanza esa frecuencia. Su límite es
obvio: sólo chequea con la Mac prendida.

No usa `StartInterval`: launchd agrupa y difiere los timers para ahorrar
energía, sobre todo con la Mac en batería. Medido con `StartInterval 120`, las
corridas salieron a 2m02s, 3m44s y 1m00s — nada parecido a un intervalo fijo.
En su lugar corre `loop.sh`, un proceso vivo que duerme `sleep 120` entre
chequeos, con `KeepAlive` para que launchd lo reviva si se cae. El intervalo se
cambia con `DUNA_INTERVALO` (segundos).

> **El proyecto NO puede vivir en `~/Desktop`.** macOS protege Desktop, Documents
> y Downloads con TCC, y un agente de launchd sin Full Disk Access no puede leer
> ahí: falla con `exit 126 / Operation not permitted` y ni siquiera llega a
> ejecutar `run.sh`. Por eso vive en **`~/showcase-duna-watch`**, con un symlink
> de cortesía en `~/Desktop/Claude_Code/showcase-duna-watch`. Si lo movés de
> vuelta a Desktop, el launchd se rompe en silencio.

Los dos corren en paralelo y **tienen estados separados** (la Mac usa
`state.json`, GitHub usa `actions/cache`), así que cuando Duna aparezca es
probable que el aviso llegue dos veces, una por cada lado. Es redundancia, no un
error. Para que compartan estado y avisen una sola vez hay que apuntar los dos al
mismo Redis con `KV_REST_API_URL` + `KV_REST_API_TOKEN`.

El log se recorta solo al pasar los 2 MB: a 720 corridas diarias si no crecería
sin techo.

## Archivos

- `api/_lib/showcase.py` — fetch + parser. Usa `HTMLParser` con tracking de
  profundidad de `<div>`: partir el HTML por regex hace que la última sección se
  coma los modales del pie y aparezcan películas fantasma.
- `api/_lib/notify.py` — un método por canal, cada uno se activa solo si tiene
  credenciales. Un canal que falla no mata a los otros.
- `api/_lib/store.py` — estado en archivo (local) o Redis REST (serverless).
- `api/_lib/core.py` — ventana de fechas, chequeo, armado del mensaje, watchdog.
- `watch.py` — CLI. `api/check.py` — el mismo chequeo como endpoint de Vercel.
