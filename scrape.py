"""Scraper de precios de ChangoApp (Jumbo, Santa Isabel) -> Supabase.

Jumbo y Santa Isabel: usa el buscador interno (Constructor.io) y recorre TODAS las categorías
para traer el catálogo completo, más términos y marcas como red de seguridad. Sin navegador.

Uso:
  python scrape.py test jumbo        # prueba rápida: no guarda nada, muestra qué encontró
  python scrape.py test all          # prueba todos los súper
  python scrape.py probe all         # igual que test all (lo usa el workflow "Probar supermercados")
  python scrape.py run jumbo         # recorre el catálogo y guarda en Supabase
  python scrape.py run all

Variables de entorno:
  SUPABASE_URL, SUPABASE_SERVICE_KEY   (solo para "run")
  MAX_PAGES (8)  DELAY (0.8)  GUARD (0.6)  FORCE (1 = ignora la protección)
"""
import json
import os
import random
import re
import sys
import time
import unicodedata
from datetime import datetime, timezone
from urllib.parse import quote

import requests

# Jumbo y Santa Isabel (Cencosud) buscan con Constructor.io. Las "key" son las claves PÚBLICAS que
# el propio frontend de cada sitio usa en el navegador (no dan acceso a cuentas). Verificadas en jul-2026
# por terceros; si dejan de funcionar, `python scrape.py test <cadena>` lo dice.
CHAINS = {
    "jumbo": {"name": "Jumbo", "base_url": "https://www.jumbo.cl",
              "cnstrc": {"host": "https://pwcdauseo-zone.cnstrc.com", "key": "key_JopvNXKS61kwGkBe"}},
    "santa-isabel": {"name": "Santa Isabel", "base_url": "https://www.santaisabel.cl",
                     "cnstrc": {"host": "https://ac.cnstrc.com", "key": "key_c73M3GMIWJ8AcNnd"}},
}
# Cadenas investigadas pero NO activas (bloquean IPs de datacenter/GitHub Actions o no hay API verificada):
#   unimarc (BFF propio, requiere IP residencial), lider (PerimeterX), tottus (antibot), acuenta (sin verificar).
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-CL,es;q=0.9",
}
MAX_PAGES = int(os.environ.get("MAX_PAGES", 8))   # páginas por término (40 productos cada una)
DELAY = float(os.environ.get("DELAY", 0.8))       # segundos entre consultas
GUARD = float(os.environ.get("GUARD", 0.6))       # si la corrida trae < 60% de lo anterior, no marca sin stock
FORCE = os.environ.get("FORCE") == "1"
MAX_FAILS = 30                                    # fallos seguidos => asumimos bloqueo y cortamos

# ---------------------------------------------------------------------------
# Términos de búsqueda por categoría. Cada término se separa por COMA, así que
# "papel higienico" o "crema dental" se buscan completos (no palabra por palabra).
# Un término aparece una sola vez (el primero que lo reclama define su categoría).
# ---------------------------------------------------------------------------
GROUPS = {
    "Despensa": """arroz, arroz grado 1, fideos, espagueti, tallarines, cabello de angel, spaghetti, penne, tornillos, lasaña,
        aceite de maravilla, aceite de oliva, aceite vegetal, vinagre, azucar, endulzante, stevia, sal, harina, harina sin polvos,
        polvos de hornear, levadura, maicena, sémola, avena, quinoa, lentejas, porotos, garbanzos, legumbres, arvejas, choclo,
        atun, jurel, sardinas, conserva de pescado, conserva de verduras, palmitos, esparragos, champiñones, aceitunas, pickles,
        salsa de tomate, pomarola, pasta de tomate, ketchup, mayonesa, mostaza, aji, salsa soya, salsa bbq, aderezo, pesto,
        pure instantaneo, sopa, caldo, sazonador, merquen, oregano, pimienta, comino, ajo en polvo, condimento, aliño,
        cafe, cafe instantaneo, cafe molido, te, té en bolsitas, yerba mate, infusion, manzanilla, cacao, chocolate en polvo,
        cereal, granola, barra de cereal, mermelada, miel, manjar, dulce de leche, nutella, crema de mani, mantequilla de mani,
        leche condensada, leche en polvo, leche evaporada, gelatina, flan, postre en polvo, galletas de agua, tostadas""",
    "Lácteos y huevos": """leche, leche entera, leche descremada, leche sin lactosa, leche de almendras, leche de soya, leche de avena,
        yogurt, yogurt griego, yogurt batido, queso, queso gauda, queso mantecoso, queso crema, queso rallado, queso fresco,
        queso mozzarella, mantequilla, margarina, crema, crema de leche, crema para batir, huevos, huevos de campo, postres lacteos,
        leche cultivada, kefir, quesillo, ricotta, requeson, chanco""",
    "Carnes y pescados": """pollo, pechuga de pollo, trutro, alitas, pavo, carne molida, lomo, lomo vetado, filete, asado, costillar,
        posta, plateada, sobrecostilla, vacuno, cerdo, chuleta, costillas de cerdo, longaniza, chorizo, salchicha, vienesa,
        jamon, jamon de pavo, mortadela, salame, pate, tocino, panceta, cordero, pescado, salmon, merluza, reineta, congrio,
        camarones, choritos, machas, locos, pulpo, calamar, mariscos, hamburguesa, albondigas, nuggets, empanadas de pino, prieta""",
    "Frutas y verduras": """frutas, verduras, manzana, platano, palta, tomate, cebolla, papa, lechuga, zanahoria, limon, naranja,
        uva, frutilla, pera, durazno, ciruela, sandia, melon, kiwi, mandarina, arandanos, cerezas, mango, piña, pimenton,
        zapallo, zapallo italiano, choclo fresco, pepino, apio, brocoli, coliflor, espinaca, acelga, repollo, betarraga,
        ajo, jengibre, cilantro, perejil, ciboulette, champiñon fresco, nueces, almendras, pasas, frutos secos, mix de frutos secos,
        ensalada lista, verduras congeladas""",
    "Panadería y dulces": """pan, pan de molde, pan hallulla, marraqueta, pan integral, pan hot dog, pan hamburguesa, tortillas, masa de pizza,
        queque, bizcocho, torta, muffins, kuchen, alfajor, galletas, galletas de chocolate, galletas rellenas, galletas dulces,
        chocolate, chocolate en barra, bombones, caramelos, chicles, gomitas, dulces, helado, helados, barquillos, turrón,
        cuchuflí, panqueques, brownies, cupcakes""",
    "Snacks": """papas fritas, chips, snack, snacks salados, ramitas, palitos, cheetos, doritos, maní, mani salado, palomitas,
        popcorn, nachos, tortilla chips, galletas saladas, crackers, mix snack, barritas, barras de proteina, frutos deshidratados""",
    "Bebidas": """agua, agua mineral, agua con gas, agua saborizada, jugo, jugo en polvo, jugo de naranja, nectar, bebida, gaseosa,
        bebida cola, bebida zero, bebida isotonica, energetica, te helado, kombucha, agua tonica, ginger ale, bebida vegetal,
        limonada, malta, cafe frio, soda""",
    "Licores": """cerveza, cerveza sin alcohol, vino, vino tinto, vino blanco, espumante, champagne, pisco, ron, whisky, vodka, gin,
        tequila, licor, cooler, sour, mistral, cabernet sauvignon, sauvignon blanc, carmenere, chardonnay, syrah, pack de cervezas""",
    "Congelados": """congelado, pizza congelada, papas prefritas, verduras congeladas bolsa, pescado congelado, nuggets de pollo,
        empanadas congeladas, helado de agua, helado de crema, hamburguesas congeladas, berries congeladas, masa congelada, platos preparados""",
    "Aseo del hogar": """detergente, detergente liquido, detergente en polvo, suavizante, lavaloza, lavalozas, cloro, limpiador, limpiador multiuso,
        limpiavidrios, desinfectante, desengrasante, cera, aromatizante, ambientador, insecticida, pastillas wc, limpia hornos,
        bolsas de basura, esponja, paño, pano de cocina, escobillon, trapero, guantes, papel aluminio, papel film, bolsas ziploc,
        papel higienico, papel confort, toalla de papel, servilletas, pañuelos desechables, quitamanchas, jabon para ropa,
        ampolleta, pilas, velas, fosforos, encendedor""",
    "Cuidado personal": """shampoo, acondicionador, crema de peinar, tintura, gel para el cabello, jabon, jabon liquido, gel de ducha,
        crema dental, pasta de dientes, cepillo de dientes, enjuague bucal, hilo dental, desodorante, antitranspirante,
        afeitar, maquinilla, espuma de afeitar, crema corporal, crema de manos, protector solar, bloqueador, maquillaje,
        labial, mascara de pestañas, esmalte, perfume, colonia, toallas higienicas, tampones, protectores diarios,
        algodon, cotonitos, toallitas humedas, vitaminas, suplemento, alcohol gel, mascarilla, pañales para adulto""",
    "Bebé": """pañales, pañales recien nacido, toallitas para bebe, formula infantil, leche de formula, papilla, cereal infantil,
        mamadera, chupete, shampoo para bebe, crema para pañal, colonia para bebe, jabon para bebe, pure para bebe""",
    "Mascotas": """alimento para perro, alimento para gato, comida de perro, comida de gato, snack para perro, snack para gato,
        arena para gato, arena sanitaria, pañales para mascotas, shampoo para mascotas, juguete para perro, collar, pipeta""",
    "Hogar": """vaso, plato, cubiertos, olla, sartén, cuchillo, tabla de cortar, taza, mug, set de cocina, contenedor, tupper,
        botella, termo, mantel, cortina, toalla, sabanas, almohada, frazada, organizador, perchas, plancha, ventilador, calefactor,
        batidora, licuadora, hervidor, tostador, microondas, cafetera, aspiradora, linterna, extension electrica"""
}

# Marcas: cada una se busca como término propio. Así se cubren productos que ningún
# término de categoría trajo, y el catálogo tiene variedad real de marcas.
BRANDS = """tucapel, miraflores, carozzi, lucchetti, colun, soprole, nestle, loncoleche, watts, iansa, chef, belmont, natura,
selecta, lobos, van camp's, nescafe, cafe caribe, bonafide, costa, mckay, savory, ideal, castaño, marco polo, fruna, evercrisp,
lays, pringles, kryspo, ramitas, coca-cola, pepsi, fanta, sprite, bilz, pap, cachantun, vital, benedictino, andina, cristal,
escudo, royal guard, corona, heineken, kunstmann, austral, stella artois, budweiser, concha y toro, santa rita, casillero del diablo,
gato, undurraga, tarapaca, misiones de rengo, alto del carmen, capel, campanario, ariel, omo, drive, skip, dove, rexona,
sedal, pantene, head & shoulders, elvive, colgate, oral-b, nivea, lifebuoy, protex, axe, gillette, elite, confort, noble, scott,
virginia, babysec, huggies, pampers, johnson's, cuisine & co, jumbo, santa isabel, la crianza, san jorge, super pollo, ariztia,
sadia, receta del abuelo, campofrio, winter, sopraval, great value, ades, alpina, danone,
activia, yoplait, nesquik, milo, ovomaltine, quaker, kellogg's, zucaritas, special k, cheerios, trix, hellmann's,
maggi, knorr, doña maria, kraft, philadelphia, president, laive, calo, la preferida, gran vidal,
nutrabien, wasil, lipton, supremo, cafe haiti, don francisco, ahmad tea, twinings,
oreo, tritón, trencito, ambrosoli, sahne-nuss, super ocho, calaf, ferrero, kinder, hershey's, m&m, snickers, toblerone,
cif, clorox, poett, mr. músculo, lysoform, sapolio, quix, magistral, dr. beckmann, vanish, comfort, downy, lenor, mimosín,
always, kotex, carefree, tena, plenitud, tresemme, loreal, garnier, maybelline, neutrogena, eucerin, vaseline, pond's,
old spice, speed stick, nuvel, sensodyne, listerine, mimaflex, dog chow, cat chow, pedigree, whiskas, master dog,
purina, royal canin, excellent, eukanuba, tamiz, sanicat, bimbo, pancho villa, san remo, regina, don vittorio,
la vencedora, zuko, kapo, yuz, andina del valle, frutos del maipo""".replace("\n", " ")

LD = re.compile(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', re.S)
PID = re.compile(r"-(\d+)/p/?$")

# ---------------------------------------------------------------------------
# Red
# ---------------------------------------------------------------------------
SESSION = requests.Session()
SESSION.headers.update(HEADERS)
_fails = 0


class Blocked(Exception):
    """Demasiados fallos seguidos: el sitio nos está bloqueando."""


def fetch(url, tries=3, as_json=False):
    global _fails
    for i in range(tries):
        try:
            r = SESSION.get(url, timeout=40)
            if r.status_code == 200:
                _fails = 0
                if as_json:
                    try:
                        return r.json()
                    except ValueError:
                        return None
                return r.text
            if r.status_code in (403, 429, 503):
                time.sleep(3 * (i + 1) + random.random())
                continue
            _fails = 0                      # 404 u otro: es de ese término, no un bloqueo
            print(f"  HTTP {r.status_code} en {url}", flush=True)
            return None
        except requests.RequestException:
            time.sleep(3 * (i + 1))
    _fails += 1
    print(f"  sin respuesta ({_fails}): {url}", flush=True)
    if _fails >= MAX_FAILS:
        raise Blocked(f"{MAX_FAILS} fallos seguidos; probable bloqueo anti-bot")
    return None


# ---------------------------------------------------------------------------
# Normalización: tamaño, precio por unidad y clave de emparejamiento
# ---------------------------------------------------------------------------
UNITS = {
    "kg": ("g", 1000), "kilo": ("g", 1000), "kilos": ("g", 1000),
    "g": ("g", 1), "gr": ("g", 1), "grs": ("g", 1), "gramo": ("g", 1), "gramos": ("g", 1),
    "l": ("ml", 1000), "lt": ("ml", 1000), "lts": ("ml", 1000), "litro": ("ml", 1000), "litros": ("ml", 1000),
    "ml": ("ml", 1), "cc": ("ml", 1), "cl": ("ml", 10),
    "un": ("un", 1), "u": ("un", 1), "und": ("un", 1), "unid": ("un", 1), "unidad": ("un", 1),
    "unidades": ("un", 1), "ud": ("un", 1), "uds": ("un", 1), "rollo": ("un", 1), "rollos": ("un", 1),
}
SIZE_RE = re.compile(
    r"(?<![\w.])(?:(\d{1,3})\s*[x×]\s*)?(\d+(?:[.,]\d+)?)\s*"
    r"(kg|kilos?|gramos?|grs?|g|litros?|lts?|l|ml|cc|cl|unidades|unidad|unid|und|uds?|un|rollos?|u)(?![a-z])",
    re.I)
STOP = {"de", "la", "el", "los", "las", "con", "en", "y", "para", "por", "a", "al", "del", "un", "una", "x"}


def strip_acc(s):
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def tokens(s):
    return [t for t in re.findall(r"[a-z0-9]+", strip_acc((s or "").lower())) if t not in STOP]


def parse_size(name):
    """Devuelve {'kind': g|ml|un, 'per': cantidad por envase, 'pack': n, 'total': total} o None."""
    best = None
    for m in SIZE_RE.finditer(name or ""):
        pack = int(m.group(1) or 1)
        kind, mult = UNITS[m.group(3).lower()]
        per = float(m.group(2).replace(",", ".")) * mult
        if per <= 0:
            continue
        cand = {"kind": kind, "per": per, "pack": pack, "total": per * pack}
        if kind != "un":
            return cand                      # prioriza peso/volumen sobre "unidades"
        if best is None:
            best = cand
    return best


def fmt_qty(v, kind):
    if kind == "g":
        return f"{v / 1000:g} kg" if v >= 1000 else f"{v:g} g"
    if kind == "ml":
        return f"{v / 1000:g} L" if v >= 1000 else f"{v:g} ml"
    return f"{v:g} un"


def size_info(name, price):
    c = parse_size(name)
    if not c:
        return None, None, None, ""
    text = (f"{c['pack']} × " if c["pack"] > 1 else "") + fmt_qty(c["per"], c["kind"])
    key = f"{c['pack']}x{c['per']:g}{c['kind']}"
    if c["kind"] == "g":
        up, label = price / c["total"] * 1000, "kg"
    elif c["kind"] == "ml":
        up, label = price / c["total"] * 1000, "L"
    elif c["total"] > 1:
        up, label = price / c["total"], "un"
    else:
        up, label = None, None
    return text, (round(up, 1) if up is not None else None), label, key


def name_key(brand, name, size_key):
    """Marca + nombre normalizado (sin acentos, sin orden) + tamaño. Sirve para unir productos sin EAN."""
    bt = tokens(brand)
    nt = [t for t in tokens(SIZE_RE.sub(" ", name or "")) if t not in bt]
    return ("nk:" + " ".join(sorted(set(bt + nt))) + ("|" + size_key if size_key else ""))[:250]


# ---------------------------------------------------------------------------
# Lectura del JSON-LD
# ---------------------------------------------------------------------------
def to_num(v):
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace("$", "").strip()
    if re.fullmatch(r"\d{1,3}(\.\d{3})+", s):    # "1.990" -> 1990
        s = s.replace(".", "")
    try:
        return float(s.replace(",", "."))
    except ValueError:
        return None


def pick_image(d, r=None):
    """Busca la imagen del producto en las claves que usan las tiendas (string, lista o dict)."""
    def norm(v):
        if isinstance(v, (list, tuple)):
            for x in v:
                n = norm(x)
                if n:
                    return n
            return None
        if isinstance(v, dict):
            for k in ("url", "src", "large", "medium", "original", "image_url"):
                n = norm(v.get(k))
                if n:
                    return n
            return None
        if isinstance(v, str):
            v = v.strip()
            if v.startswith("//"):
                v = "https:" + v
            return v if v.startswith("http") else None
        return None
    for src in (d or {}, r or {}):
        for k in ("image_url", "imageUrl", "imageURL", "image", "images", "thumbnail", "img", "picture"):
            n = norm(src.get(k))
            if n:
                return n
    return None


def get_ean(it, offers):
    for src in (it, offers):
        for k in ("gtin13", "gtin", "gtin12", "gtin14", "gtin8"):
            v = re.sub(r"\D", "", str(src.get(k) or ""))
            if 8 <= len(v) <= 14:
                return v.lstrip("0")
    return None


def get_prices(offers):
    price = to_num(offers.get("price")) or to_num(offers.get("lowPrice"))
    orig = to_num(offers.get("highPrice"))
    specs = offers.get("priceSpecification") or []
    for sp in (specs if isinstance(specs, list) else [specs]):
        if isinstance(sp, dict) and "list" in str(sp.get("priceType", "")).lower():
            orig = max(orig or 0, to_num(sp.get("price")) or 0) or orig
    if price and orig and price < orig <= price * 3:   # tope por si trae datos raros
        return round(price), round(orig)
    return (round(price) if price else None), (round(price) if price else None)


def item_lists(d):
    if isinstance(d, list):
        for x in d:
            yield from item_lists(x)
    elif isinstance(d, dict):
        if d.get("@type") == "ItemList":
            yield d
        for x in d.get("@graph", []) or []:
            yield from item_lists(x)


def parse(html):
    out = []
    for blob in LD.findall(html):
        try:
            d = json.loads(blob)
        except ValueError:
            continue
        for lst in item_lists(d):
            for el in lst.get("itemListElement", []):
                it = el.get("item") or {}
                url = it.get("url") or el.get("url") or ""
                name = it.get("name") or el.get("name")
                offers = it.get("offers") or {}
                if isinstance(offers, list):
                    offers = offers[0] if offers else {}
                price, orig = get_prices(offers)
                if not (url and name and price):
                    continue
                brand = it.get("brand")
                brand = brand.get("name") if isinstance(brand, dict) else brand
                img = it.get("image")
                img = img[0] if isinstance(img, list) and img else img
                m = PID.search(url)
                ean = get_ean(it, offers)
                size_text, unit_price, unit_label, size_key = size_info(name, price)
                nk = name_key(brand, name, size_key)
                out.append({
                    "external_id": m.group(1) if m else url,
                    "name": name,
                    "brand": brand,
                    "ean": ean,
                    "external_url": url,
                    "image_url": img.replace("-250-250", "-500-500") if isinstance(img, str) else None,
                    "current_price": price,
                    "original_price": orig,
                    "is_offer": orig > price,
                    "in_stock": "InStock" in str(offers.get("availability", "")),
                    "size_text": size_text,
                    "unit_price": unit_price,
                    "unit_label": unit_label,
                    "name_key": nk,
                    "match_key": ("ean:" + ean) if ean else nk,
                })
    return out


# ---------------------------------------------------------------------------
# Constructor.io (Jumbo, Santa Isabel)
# ---------------------------------------------------------------------------
CNSTRC_PER_PAGE = 100
CNSTRC_MAX_PAGES = int(os.environ.get("CNSTRC_MAX_PAGES", 80))   # 80 x 100 = 8.000 por categoría


def cnstrc_url(cfg, path, page=1, per=CNSTRC_PER_PAGE):
    c = cfg["cnstrc"]
    return (f"{c['host']}/{path}?key={c['key']}&i=00000000-0000-4000-8000-000000000001&s=1"
            f"&page={page}&num_results_per_page={per}")


def parse_cnstrc(resp, base_url):
    """Convierte la respuesta de Constructor.io (search/browse) en filas de store_products."""
    out = []
    for r in ((resp or {}).get("response") or {}).get("results") or []:
        d = r.get("data") or {}
        name = r.get("value") or d.get("ProductName")
        price = to_num(d.get("sellingPrice"))
        sku = d.get("id") or d.get("ProductId")
        if not (name and price and sku):
            continue
        orig = max((to_num(d.get(k)) or 0) for k in ("listPrice", "price", "originalPrice"))
        if not (price < orig <= price * 3):
            orig = price
        url = d.get("url") or ""
        if url.startswith("/"):
            url = base_url + url
        brand = d.get("BrandName") or None
        price, orig = round(price), round(orig)
        # tamaño: primero el nombre; si no, la unidad de medida que informa la tienda
        size_text, unit_price, unit_label, size_key = size_info(name, price)
        nk = name_key(brand, name, size_key)
        ean = get_ean(d, {})
        stock = str(d.get("stockLevel") or "").lower()
        out.append({
            "external_id": str(sku),
            "name": name,
            "brand": brand,
            "ean": ean,
            "external_url": url or None,
            "image_url": pick_image(d, r),
            "current_price": price,
            "original_price": orig,
            "is_offer": orig > price,
            "in_stock": not (d.get("outOfStock") is True or "out" in stock),
            "size_text": size_text,
            "unit_price": unit_price,
            "unit_label": unit_label,
            "name_key": nk,
            "match_key": ("ean:" + ean) if ean else nk,
        })
    return out


def leaf_groups(groups, top=None):
    """Aplana el árbol de categorías: devuelve [(group_id, nombre_categoria_principal)] de las hojas."""
    out = []
    for g in groups or []:
        gid, name = g.get("group_id"), g.get("display_name")
        t = top or name
        kids = g.get("children") or []
        if kids:
            out += leaf_groups(kids, t)
        elif gid:
            out.append((str(gid), t))
    return out


def crawl_cnstrc(slug):
    cfg = CHAINS[slug]
    base = cfg["base_url"]
    seen = {}

    def add(items, cat):
        for it in items:
            cur = seen.get(it["external_id"])
            if cur is None:
                it["category"] = cat
                seen[it["external_id"]] = it
            elif not cur.get("category") and cat:
                cur["category"] = cat

    try:
        # 1) árbol de categorías (viene en cualquier respuesta de búsqueda)
        first = fetch(cnstrc_url(cfg, "search/leche", 1, 1), as_json=True)
        groups = ((first or {}).get("response") or {}).get("groups") or []
        leaves = leaf_groups(groups)
        print(f"{cfg['name']}: {len(leaves)} categorías para recorrer", flush=True)
        # 2) cada categoría completa, paginada
        for n, (gid, top) in enumerate(leaves, 1):
            for page in range(1, CNSTRC_MAX_PAGES + 1):
                resp = fetch(cnstrc_url(cfg, f"browse/group_id/{gid}", page), as_json=True)
                items = parse_cnstrc(resp, base)
                if not items:
                    break
                add(items, top)
                if len(items) < CNSTRC_PER_PAGE * 0.5 and page > 1:
                    break
                time.sleep(0.35 + random.random() * 0.2)
            if n % 10 == 0 or n == len(leaves):
                print(f"[{n}/{len(leaves)}] {len(seen)} productos acumulados", flush=True)
        # 3) red de seguridad: términos y marcas (por si alguna categoría quedó fuera del árbol)
        if os.environ.get("EXTRA_TERMS", "1") == "1":
            for n, (term, group) in enumerate(all_terms().items(), 1):
                for page in range(1, 4):
                    resp = fetch(cnstrc_url(cfg, f"search/{quote(term)}", page), as_json=True)
                    items = parse_cnstrc(resp, base)
                    if not items:
                        break
                    add(items, group)
                    if len(items) < CNSTRC_PER_PAGE * 0.5:
                        break
                    time.sleep(0.35)
                if n % 50 == 0:
                    print(f"  términos {n}: {len(seen)} productos acumulados", flush=True)
    except Blocked as e:
        print(f"AVISO: {e}. Se guarda lo recolectado hasta aquí.", flush=True)
    for it in seen.values():
        it["category"] = it.get("category") or "Otros"
    return list(seen.values())


def test_cnstrc(slug):
    cfg = CHAINS[slug]
    print(f"=== {cfg['name']} (Constructor.io) ===")
    resp = fetch(cnstrc_url(cfg, "search/leche", 1, 20), as_json=True)
    items = parse_cnstrc(resp, cfg["base_url"])
    groups = ((resp or {}).get("response") or {}).get("groups") or []
    total = ((resp or {}).get("response") or {}).get("total_num_results")
    print(f"productos en la página: {len(items)} · total para 'leche': {total} · categorías hoja: {len(leaf_groups(groups))}")
    for i in items[:5]:
        print("  ", i["name"], "|", i["brand"], "|", i["current_price"], "| lista:", i["original_price"],
              "| tamaño:", i["size_text"], "| $/", i["unit_label"], i["unit_price"], "| stock:", i["in_stock"])
    if items:
        con_img = sum(bool(i["image_url"]) for i in items)
        print(f"con imagen: {con_img}/{len(items)} · ejemplo: {next((i['image_url'] for i in items if i['image_url']), '(ninguna)')}")
        if not con_img and resp:
            ejemplo = ((resp.get("response") or {}).get("results") or [{}])[0]
            print("AVISO: ningún producto trae imagen. Claves que sí llegan:", sorted((ejemplo.get("data") or {}).keys()))
    ok = bool(items)
    print("RESULTADO:", "FUNCIONA" if ok else "NO FUNCIONA (la clave pública pudo cambiar o el sitio bloquea esta IP)")
    return ok


# ---------------------------------------------------------------------------
# Recorrido
# ---------------------------------------------------------------------------
def all_terms():
    terms = {}
    for group, txt in GROUPS.items():
        for t in (x.strip() for x in txt.replace("\n", " ").split(",")):
            if t:
                terms.setdefault(t, group)
    for b in (x.strip() for x in BRANDS.split(",")):
        if b:
            terms.setdefault(b, None)       # marcas: la categoría viene de otro término o queda "Otros"
    return terms


def search_url(base, term, page):
    return f"{base}/busqueda?ft={quote(term)}" + (f"&page={page}" if page > 1 else "")


def crawl(base):
    seen, terms = {}, all_terms()
    try:
        for n, (term, group) in enumerate(terms.items(), 1):
            prev = None
            for page in range(1, MAX_PAGES + 1):
                html = fetch(search_url(base, term, page))
                items = parse(html) if html else []
                ids = [i["external_id"] for i in items]
                if not items or ids == prev:     # sin resultados o la paginación repite lo mismo
                    break
                for it in items:
                    cur = seen.get(it["external_id"])
                    if cur is None:
                        it["category"] = group
                        seen[it["external_id"]] = it
                    elif cur["category"] is None and group:
                        cur["category"] = group
                prev = ids
                if len(items) < 30:              # última página
                    break
                time.sleep(DELAY + random.random() * 0.4)
            if n % 10 == 0 or n == len(terms):
                print(f"[{n}/{len(terms)}] {term}: {len(seen)} productos acumulados", flush=True)
            time.sleep(DELAY)
    except Blocked as e:
        print(f"AVISO: {e}. Se guarda lo recolectado hasta aquí.", flush=True)
    for it in seen.values():
        it["category"] = it["category"] or "Otros"
    return list(seen.values())


def test(slug):
    if CHAINS[slug].get("cnstrc"):
        return test_cnstrc(slug)
    base = CHAINS[slug]["base_url"]
    print(f"=== {CHAINS[slug]['name']} ===")
    firsts, allitems = [], []
    for page in (1, 2):
        html = fetch(search_url(base, "leche", page))
        items = parse(html) if html else []
        allitems += items
        firsts.append([i["external_id"] for i in items])
        print(f"página {page}: {len(items)} productos")
    for i in allitems[:5]:
        print("  ", i["name"], "|", i["brand"], "|", i["current_price"], "| ean:", i["ean"],
              "| tamaño:", i["size_text"], "| $/", i["unit_label"], i["unit_price"], "| oferta:", i["is_offer"])
    if allitems:
        n = len(allitems)
        print(f"con EAN: {sum(bool(i['ean']) for i in allitems)}/{n} · con tamaño: "
              f"{sum(bool(i['size_text']) for i in allitems)}/{n} · en oferta: {sum(i['is_offer'] for i in allitems)}/{n}")
    if firsts[0] and firsts[0] == firsts[1]:
        print("AVISO: la página 2 repite la 1; la paginación no funciona con ?page=")
    ok = bool(firsts[0])
    print("RESULTADO:", "FUNCIONA" if ok else "NO FUNCIONA")
    return ok


# ---------------------------------------------------------------------------
# Guardado en Supabase
# ---------------------------------------------------------------------------
def save(slug, rows):
    from supabase import create_client

    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])
    cfg = CHAINS[slug]
    sid = (sb.table("supermarkets")
           .upsert({"slug": slug, "name": cfg["name"], "base_url": cfg["base_url"]}, on_conflict="slug")
           .execute().data[0]["id"])

    old, start = {}, 0
    while True:
        chunk = (sb.table("store_products").select("external_id,current_price,in_stock")
                 .eq("supermarket_id", sid).range(start, start + 999).execute().data)
        old.update({c["external_id"]: c for c in chunk})
        if len(chunk) < 1000:
            break
        start += 1000
    prev_in_stock = sum(1 for c in old.values() if c["in_stock"])

    now = datetime.now(timezone.utc).isoformat()
    hist = []
    try:
        for i in range(0, len(rows), 500):
            batch = [{**r, "supermarket_id": sid, "updated_at": now} for r in rows[i:i + 500]]
            res = sb.table("store_products").upsert(batch, on_conflict="supermarket_id,external_id").execute().data
            hist += [{"store_product_id": x["id"], "price": x["current_price"]}
                     for x in res if (old.get(x["external_id"]) or {}).get("current_price") != x["current_price"]]
    except Exception as e:
        sys.exit(f"ERROR al guardar: {e}\n¿Ya ejecutaste migracion_001.sql en el SQL Editor de Supabase?")
    for i in range(0, len(hist), 1000):
        sb.table("price_history").insert(hist[i:i + 1000]).execute()

    current = {r["external_id"] for r in rows}
    gone = [e for e, c in old.items() if e not in current and c["in_stock"]]
    suspicious = prev_in_stock >= 200 and len(rows) < GUARD * prev_in_stock and not FORCE
    if suspicious:
        print(f"PROTECCIÓN: hoy llegaron {len(rows)} productos y antes había {prev_in_stock} con stock. "
              f"No se marcan {len(gone)} como sin stock (¿bloqueo o corrida parcial?).", flush=True)
    else:
        for i in range(0, len(gone), 200):
            (sb.table("store_products").update({"in_stock": False})
             .eq("supermarket_id", sid).in_("external_id", gone[i:i + 200]).execute())

    sb.rpc("link_products").execute()
    print(f"{cfg['name']}: {len(rows)} productos, {len(hist)} cambios de precio, "
          f"{0 if suspicious else len(gone)} marcados sin stock", flush=True)
    return not suspicious


def run(slug):
    rows = crawl_cnstrc(slug) if CHAINS[slug].get("cnstrc") else crawl(CHAINS[slug]["base_url"])
    if not rows:
        print(f"ERROR: 0 productos en {slug}. El sitio cambió o bloqueó el acceso.")
        return False
    return save(slug, rows)


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in ("test", "run", "probe") or (sys.argv[2] not in CHAINS and sys.argv[2] != "all"):
        sys.exit(__doc__)
    cmd = sys.argv[1]
    chains = list(CHAINS) if sys.argv[2] == "all" else [sys.argv[2]]
    ok = all([(run if cmd == "run" else test)(c) for c in chains])
    sys.exit(0 if ok else 1)
