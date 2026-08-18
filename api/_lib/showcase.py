"""Scraper de la cartelera de todoshowcase.com — parser + modelo de datos.

Solo stdlib (corre con cualquier python3 >= 3.7, sin pip install).
"""
import html
import json
import re
import ssl
import unicodedata
import urllib.error
import urllib.request
from html.parser import HTMLParser

HOME_URL = "https://todoshowcase.com/"
ENTRADAS_URL = "https://entradas.todoshowcase.com/showcase/"

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# id del <div> de cada cartelera en la home. El que nos importa es 40219.
SECTIONS = {
    "cartelera_cine_40219": "IMAX THEATRE (Norcenter)",
    "cartelera_cine_40213": "Showcase Norcenter",
    "cartelera_cine_40212": "Showcase Belgrano",
    "cartelera_cine_40214": "Showcase Haedo",
    "cartelera_cine_40215": "Showcase Quilmes",
    "cartelera_cine_40216": "Showcase Cordoba Villa Cabrera",
    "cartelera_cine_40217": "Showcase Villa Allende",
    "cartelera_cine_40218": "Showcase Rosario",
    "cartelera_actual": "Todas las salas",
    "cartelera_anticipada": "Venta anticipada (todas)",
}

TARGET_SECTION = "cartelera_cine_40219"
TARGET_HOUSE_ID = "3250"


class Film:
    __slots__ = ("filmid", "title", "tags", "url", "house_id")

    def __init__(self, filmid, title, tags, url, house_id):
        self.filmid = filmid
        self.title = title
        self.tags = tags
        self.url = url
        self.house_id = house_id

    @property
    def anticipada(self):
        return any("anticipada" in t.lower() for t in self.tags)

    @property
    def key(self):
        return self.filmid or _fold(self.title)

    def as_dict(self):
        return {
            "filmid": self.filmid,
            "title": self.title,
            "tags": self.tags,
            "url": self.url,
            "house_id": self.house_id,
            "anticipada": self.anticipada,
        }

    def __repr__(self):
        return "Film(%s, %r, %r)" % (self.filmid, self.title, self.tags)


class CarteleraParser(HTMLParser):
    """Extrae los .boxfilm de cada <div id="cartelera_*" class="div-cartelera">.

    Trackea profundidad de <div> para cerrar cada seccion en el lugar correcto:
    partir el HTML por regex hace que la ultima seccion se coma los modales del
    pie de pagina.
    """

    def __init__(self):
        HTMLParser.__init__(self)
        self.sections = {}
        self._div_depth = 0
        self._sec_id = None
        self._sec_depth = None
        self._box_depth = None
        self._box = None
        self._sink = None  # "tag" | "title" | None
        self._sink_depth = None

    # -- helpers -----------------------------------------------------------
    @staticmethod
    def _attr(attrs, name):
        for k, v in attrs:
            if k == name:
                return v or ""
        return ""

    def _flush_box(self):
        if self._box is None:
            return
        title = _squash(self._box["title"])
        tags = [_squash(t) for t in self._box["tags"]]
        tags = [t for t in tags if t]
        # El sitio repite el titulo como "tag" cuando no hay etiqueta real.
        tags = [t for t in tags if _fold(t) != _fold(title)]
        if title:
            self.sections[self._sec_id].append(
                Film(self._box["filmid"], title, tags, self._box["url"], self._box["house_id"])
            )
        self._box = None
        self._box_depth = None

    # -- HTMLParser --------------------------------------------------------
    def handle_starttag(self, tag, attrs):
        if tag == "a" and self._box is not None:
            href = self._attr(attrs, "href")
            if "filmid=" in href:
                m = re.search(r"filmid=(\d+)", href)
                if m and not self._box["filmid"]:
                    self._box["filmid"] = m.group(1)
                h = re.search(r"house_id=(\d+)", href)
                if h and not self._box["house_id"]:
                    self._box["house_id"] = h.group(1)
                if not self._box["url"]:
                    self._box["url"] = html.unescape(href)

        if tag != "div":
            return
        self._div_depth += 1
        cls = self._attr(attrs, "class")
        did = self._attr(attrs, "id")

        if self._sec_id is None:
            if did in SECTIONS and "div-cartelera" in cls:
                self._sec_id = did
                self._sec_depth = self._div_depth
                self.sections.setdefault(did, [])
            return

        if self._box is None:
            if "boxfilm" in cls.split():
                self._box = {"filmid": "", "title": "", "tags": [], "url": "", "house_id": ""}
                self._box_depth = self._div_depth
            return

        if self._sink is None:
            if "tag-container" in cls:
                self._sink, self._sink_depth = "tag", self._div_depth
                self._box["tags"].append("")
            elif "titulo-pelicula" in cls:
                self._sink, self._sink_depth = "title", self._div_depth

    def handle_endtag(self, tag):
        if tag != "div":
            return
        if self._sink is not None and self._div_depth == self._sink_depth:
            self._sink = self._sink_depth = None
        if self._box is not None and self._div_depth == self._box_depth:
            self._flush_box()
        if self._sec_id is not None and self._div_depth == self._sec_depth:
            self._sec_id = self._sec_depth = None
        self._div_depth -= 1

    def handle_data(self, data):
        if self._box is None or self._sink is None:
            return
        if self._sink == "title":
            self._box["title"] += data
        else:
            self._box["tags"][-1] += " " + data


def _squash(s):
    return re.sub(r"\s+", " ", html.unescape(s or "")).strip()


def _fold(s):
    """minusculas + sin tildes, para comparar titulos."""
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s).strip().lower()


def fetch(url, timeout=30):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "es-AR,es;q=0.9",
        "Cache-Control": "no-cache",
    })
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
        raw = r.read()
    charset = "utf-8"
    return raw.decode(charset, errors="replace")


def scrape_home(html_text=None):
    """-> dict {section_id: [Film, ...]}"""
    if html_text is None:
        html_text = fetch(HOME_URL)
    p = CarteleraParser()
    p.feed(html_text)
    return p.sections


def scrape_entradas_titles(html_text=None):
    """Titulos del sitio de venta (global, no por complejo). Señal temprana."""
    if html_text is None:
        html_text = fetch(ENTRADAS_URL)
    txt = re.sub(r"<script.*?</script>", " ", html_text, flags=re.S)
    txt = re.sub(r"<style.*?</style>", " ", txt, flags=re.S)
    out = set()
    for m in re.finditer(r"<h[1-5][^>]*>(.*?)</h[1-5]>", txt, re.S):
        t = _squash(re.sub(r"<[^>]+>", " ", m.group(1)))
        if 2 < len(t) < 120:
            out.add(t)
    for m in re.finditer(r'title="([^"]{3,120})"', txt):
        out.add(_squash(m.group(1)))
    return sorted(out)


def match_films(films, patterns):
    """films: [Film]; patterns: [regex compilada] -> [Film] que matchean."""
    hits = []
    for f in films:
        folded = _fold(f.title)
        if any(p.search(folded) for p in patterns):
            hits.append(f)
    return hits


def build_patterns(keywords):
    pats = []
    for kw in keywords:
        kw = _fold(kw)
        if not kw:
            continue
        pats.append(re.compile(r"(?<![a-z0-9])" + re.escape(kw) + r"s?(?![a-z0-9])"))
    return pats
