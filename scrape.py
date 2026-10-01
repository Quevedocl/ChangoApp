"""Scraper de precios de supermercados -> Supabase (motor VTEX).

Uso:
  python scrape.py probe jumbo   # comprueba si la web expone el catálogo VTEX
  python scrape.py run jumbo     # descarga TODO el catálogo y actualiza precios

Variables de entorno: SUPABASE_URL, SUPABASE_SERVICE_KEY
"""
import os
import sys
import time
from datetime import datetime, timezone

import requests

CHAINS = {
    "jumbo": {"name": "Jumbo", "base_url": "https://www.jumbo.cl"},
    "santa-isabel": {"name": "Santa Isabel", "base_url": "https://www.santaisabel.cl"},
}
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; ComparadorBot/1.0; +contacto@tudominio.cl)",
    "Accept": "application/json",
}
PAGE = 50      # máximo de VTEX por consulta
MAX_OFFSET = 2500  # VTEX no entrega más allá de ~2500 por búsqueda
DELAY = 0.4    # segundos entre consultas (sé amable con el sitio)


def get(url, params=None, tries=4):
    for i in range(tries):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=30)
            if r.status_code in (200, 206):  # VTEX responde 206 en listados
                return r.json()
            if r.status_code in (429, 503):
                time.sleep(2 ** (i + 1))
                continue
            r.raise_for_status()
        except requests.RequestException:
            if i == tries - 1:
                raise
            time.sleep(2 ** (i + 1))
    return []


def leaf_categories(base):
    """Categorías hoja: cada una queda bajo el límite de 2500 productos."""
    tree = get(f"{base}/api/catalog_system/pub/category/tree/4")
    out = []

    def walk(nodes, path):
        for n in nodes:
            p = path + [n["name"]]
            if n.get("children"):
                walk(n["children"], p)
            else:
                out.append((n["id"], " > ".join(p)))

    walk(tree, [])
    return out


def parse(item, base, category):
    skus = item.get("items") or [{}]
    sku = skus[0]
    sellers = sku.get("sellers") or [{}]
    seller = next((s for s in sellers if s.get("sellerDefault")), sellers[0])
    offer = seller.get("commertialOffer", {})
    price, lst = offer.get("Price"), offer.get("ListPrice")
    if not price:
        return None
    link = item.get("link") or ""
    if link.startswith("/"):
        link = base + link
    images = sku.get("images") or [{}]
    return {
        "external_id": str(item["productId"]),
        "name": item.get("productName"),
        "brand": item.get("brand"),
        "ean": (sku.get("ean") or "").strip() or None,
        "category": category,
        "external_url": link,
        "image_url": images[0].get("imageUrl"),
        "current_price": round(price),
        "original_price": round(lst) if lst else round(price),
        "is_offer": bool(lst and lst > price),
        "in_stock": (offer.get("AvailableQuantity") or 0) > 0,
    }


def crawl(base):
    seen = {}
    cats = leaf_categories(base)
    for n, (cid, path) in enumerate(cats, 1):
        start = 0
        while True:
            data = get(
                f"{base}/api/catalog_system/pub/products/search",
                {"fq": f"C:{cid}", "_from": start, "_to": start + PAGE - 1},
            )
            for it in data:
                row = parse(it, base, path)
                if row:
                    seen[row["external_id"]] = row
            if len(data) < PAGE or start + PAGE >= MAX_OFFSET:
                break
            start += PAGE
            time.sleep(DELAY)
        print(f"[{n}/{len(cats)}] {path}: {len(seen)} productos acumulados", flush=True)
        time.sleep(DELAY)
    return list(seen.values())


def save(slug, rows):
    from supabase import create_client

    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])
    cfg = CHAINS[slug]
    sid = (
        sb.table("supermarkets")
        .upsert({"slug": slug, "name": cfg["name"], "base_url": cfg["base_url"]}, on_conflict="slug")
        .execute()
        .data[0]["id"]
    )

    # precios actuales, para registrar historial solo cuando cambian
    old, start = {}, 0
    while True:
        chunk = (
            sb.table("store_products")
            .select("external_id,current_price")
            .eq("supermarket_id", sid)
            .range(start, start + 999)
            .execute()
            .data
        )
        old.update({c["external_id"]: c["current_price"] for c in chunk})
        if len(chunk) < 1000:
            break
        start += 1000

    now = datetime.now(timezone.utc).isoformat()
    hist = []
    for i in range(0, len(rows), 500):
        batch = [{**r, "supermarket_id": sid, "updated_at": now} for r in rows[i : i + 500]]
        res = sb.table("store_products").upsert(batch, on_conflict="supermarket_id,external_id").execute().data
        hist += [
            {"store_product_id": x["id"], "price": x["current_price"]}
            for x in res
            if old.get(x["external_id"]) != x["current_price"]
        ]
    for i in range(0, len(hist), 1000):
        sb.table("price_history").insert(hist[i : i + 1000]).execute()

    # productos que ya no aparecen en la web -> sin stock
    current = {r["external_id"] for r in rows}
    gone = [e for e in old if e not in current]
    for i in range(0, len(gone), 200):
        (
            sb.table("store_products")
            .update({"in_stock": False})
            .eq("supermarket_id", sid)
            .in_("external_id", gone[i : i + 200])
            .execute()
        )

    sb.rpc("link_by_ean").execute()
    print(f"{cfg['name']}: {len(rows)} productos, {len(hist)} cambios de precio, {len(gone)} sin stock")


def probe(slug):
    base = CHAINS[slug]["base_url"]
    try:
        cats = leaf_categories(base)
        print(f"OK: {len(cats)} categorías hoja. Ejemplo: {cats[0]}")
        data = get(
            f"{base}/api/catalog_system/pub/products/search",
            {"fq": f"C:{cats[0][0]}", "_from": 0, "_to": 4},
        )
        print(f"OK: {len(data)} productos de prueba")
        if data:
            print(parse(data[0], base, cats[0][1]))
    except Exception as e:
        print("FALLÓ:", e)
        print("Esta web probablemente no usa VTEX o bloquea el acceso. Hay que usar otro método.")


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[2] not in CHAINS or sys.argv[1] not in ("probe", "run"):
        sys.exit(__doc__)
    cmd, chain = sys.argv[1], sys.argv[2]
    if cmd == "probe":
        probe(chain)
    else:
        save(chain, crawl(CHAINS[chain]["base_url"]))
