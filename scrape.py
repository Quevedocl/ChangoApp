"""Scraper de precios (Jumbo, Santa Isabel) -> Supabase.
 
Lee los productos que cada web incluye en el HTML de sus páginas de búsqueda (JSON-LD).
 
Uso:
  python scrape.py test jumbo   # prueba rápida: no guarda nada, muestra qué encontró
  python scrape.py run jumbo    # recorre el catálogo y guarda en Supabase
 
Variables de entorno para "run": SUPABASE_URL, SUPABASE_SERVICE_KEY
"""
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from urllib.parse import quote
 
import requests
 
CHAINS = {
    "jumbo": {"name": "Jumbo", "base_url": "https://www.jumbo.cl"},
    "santa-isabel": {"name": "Santa Isabel", "base_url": "https://www.santaisabel.cl"},
}
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-CL,es;q=0.9",
}
MAX_PAGES = 6   # páginas por término de búsqueda (40 productos cada una)
DELAY = 0.8     # segundos entre consultas, para no sobrecargar el sitio
 
# Términos de búsqueda: recorren el catálogo por palabras. Agrega más para ampliar la cobertura.
TERMS = """leche yogurt queso mantequilla crema huevos margarina arroz fideos aceite azucar sal harina
legumbres lentejas porotos garbanzos atun conserva salsa tomate mayonesa ketchup mostaza aceitunas
cafe te yerba chocolate cereal avena galletas snack papas chips mani frutos secos mermelada miel
pan masa pizza empanada jamon salchicha vienesa tocino pollo carne vacuno cerdo pavo cordero pescado
salmon merluza camaron marisco hamburguesa nuggets congelado helado frutas verduras manzana platano
palta tomate cebolla papa lechuga zanahoria limon naranja uva frutilla agua jugo bebida gaseosa cerveza
vino pisco ron whisky espumante energetica isotonica detergente suavizante lavaloza cloro limpiador
desinfectante papel higienico toalla servilleta pañal toallitas shampoo acondicionador jabon crema dental
cepillo desodorante afeitar maquillaje perfume protector alimento perro gato arena mascota vitaminas
pilas ampolleta bolsas basura esponja panal bebe formula galleta dulce caramelo chicle alfajor""".split()
 
LD = re.compile(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', re.S)
PID = re.compile(r"-(\d+)/p/?$")
 
 
def fetch(url, tries=3):
    for i in range(tries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=40)
            if r.status_code == 200:
                return r.text
            if r.status_code in (403, 429, 503):
                time.sleep(3 * (i + 1))
                continue
            print(f"  HTTP {r.status_code} en {url}", flush=True)
            return None
        except requests.RequestException:
            time.sleep(3 * (i + 1))
    print(f"  sin respuesta: {url}", flush=True)
    return None
 
 
def parse(html):
    out = []
    for blob in LD.findall(html):
        try:
            d = json.loads(blob)
        except ValueError:
            continue
        if not isinstance(d, dict) or d.get("@type") != "ItemList":
            continue
        for el in d.get("itemListElement", []):
            it = el.get("item") or {}
            url = it.get("url") or el.get("url") or ""
            name = it.get("name") or el.get("name")
            offers = it.get("offers") or {}
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            price = offers.get("price") or offers.get("lowPrice")
            if not (url and name and price):
                continue
            brand = it.get("brand")
            brand = brand.get("name") if isinstance(brand, dict) else brand
            img = it.get("image")
            img = img[0] if isinstance(img, list) and img else img
            m = PID.search(url)
            out.append({
                "external_id": m.group(1) if m else url,
                "name": name,
                "brand": brand,
                "external_url": url,
                "image_url": img.replace("-250-250", "-500-500") if isinstance(img, str) else None,
                "current_price": round(float(price)),
                "original_price": round(float(price)),
                "is_offer": False,
                "in_stock": "InStock" in str(offers.get("availability", "")),
            })
    return out
 
 
def search_url(base, term, page):
    return f"{base}/busqueda?ft={quote(term)}" + (f"&page={page}" if page > 1 else "")
 
 
def crawl(base):
    seen = {}
    for n, term in enumerate(TERMS, 1):
        prev = None
        for page in range(1, MAX_PAGES + 1):
            html = fetch(search_url(base, term, page))
            items = parse(html) if html else []
            ids = [i["external_id"] for i in items]
            if not items or ids == prev:   # sin resultados o la paginación repite lo mismo
                break
            for it in items:
                it["category"] = term
                seen.setdefault(it["external_id"], it)
            prev = ids
            if len(items) < 30:            # última página
                break
            time.sleep(DELAY)
        print(f"[{n}/{len(TERMS)}] {term}: {len(seen)} productos acumulados", flush=True)
        time.sleep(DELAY)
    return list(seen.values())
 
 
def test(slug):
    base = CHAINS[slug]["base_url"]
    print(f"=== {CHAINS[slug]['name']} ===")
    firsts = []
    for page in (1, 2):
        html = fetch(search_url(base, "leche", page))
        items = parse(html) if html else []
        firsts.append([i["external_id"] for i in items])
        print(f"página {page}: {len(items)} productos", [(i["name"], i["current_price"]) for i in items[:3]])
    if firsts[0] and firsts[0] == firsts[1]:
        print("AVISO: la página 2 repite la 1; la paginación no funciona con ?page=")
    print("RESULTADO:", "FUNCIONA" if firsts[0] else "NO FUNCIONA")
 
 
def save(slug, rows):
    from supabase import create_client
 
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])
    cfg = CHAINS[slug]
    sid = (sb.table("supermarkets")
           .upsert({"slug": slug, "name": cfg["name"], "base_url": cfg["base_url"]}, on_conflict="slug")
           .execute().data[0]["id"])
 
    old, start = {}, 0
    while True:
        chunk = (sb.table("store_products").select("external_id,current_price")
                 .eq("supermarket_id", sid).range(start, start + 999).execute().data)
        old.update({c["external_id"]: c["current_price"] for c in chunk})
        if len(chunk) < 1000:
            break
        start += 1000
 
    now = datetime.now(timezone.utc).isoformat()
    hist = []
    for i in range(0, len(rows), 500):
        batch = [{**r, "supermarket_id": sid, "updated_at": now} for r in rows[i:i + 500]]
        res = sb.table("store_products").upsert(batch, on_conflict="supermarket_id,external_id").execute().data
        hist += [{"store_product_id": x["id"], "price": x["current_price"]}
                 for x in res if old.get(x["external_id"]) != x["current_price"]]
    for i in range(0, len(hist), 1000):
        sb.table("price_history").insert(hist[i:i + 1000]).execute()
 
    current = {r["external_id"] for r in rows}
    gone = [e for e in old if e not in current]
    for i in range(0, len(gone), 200):
        (sb.table("store_products").update({"in_stock": False})
         .eq("supermarket_id", sid).in_("external_id", gone[i:i + 200]).execute())
 
    sb.rpc("link_products").execute()
    print(f"{cfg['name']}: {len(rows)} productos, {len(hist)} cambios de precio, {len(gone)} no aparecieron hoy")
 
 
if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in ("test", "run") or sys.argv[2] not in CHAINS:
        sys.exit(__doc__)
    cmd, chain = sys.argv[1], sys.argv[2]
    if cmd == "test":
        test(chain)
    else:
        rows = crawl(CHAINS[chain]["base_url"])
        if not rows:
            sys.exit("ERROR: 0 productos. El sitio cambió o bloqueó el acceso.")
        save(chain, rows)
