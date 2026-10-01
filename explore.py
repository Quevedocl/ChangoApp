"""Explora cómo leer el catálogo de un súper desde su HTML (sin navegador).
Uso: python explore.py jumbo
"""
import json
import re
import sys
 
import requests
 
SITES = {"jumbo": "https://www.jumbo.cl", "santa-isabel": "https://www.santaisabel.cl"}
H = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-CL,es;q=0.9",
}
 
 
def get(url):
    return requests.get(url, headers=H, timeout=30)
 
 
def jsonld(html):
    out = []
    for m in re.findall(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', html, re.S):
        try:
            out.append(json.loads(m))
        except Exception:
            pass
    return out
 
 
def items(html):
    for d in jsonld(html):
        if isinstance(d, dict) and d.get("@type") == "ItemList":
            return d.get("itemListElement", []), d.get("numberOfItems")
    return [], None
 
 
def step(title, fn):
    print(f"\n=== {title} ===")
    try:
        fn()
    except Exception as e:
        print("ERROR:", repr(e)[:300])
 
 
def main(slug):
    base = SITES[slug]
    state = {}
 
    def t_search():
        for q in ("busqueda?ft=leche", "busqueda?ft=leche&page=2", "busqueda?ft=leche&page=3"):
            r = get(f"{base}/{q}")
            its, n = items(r.text)
            names = [i.get("name") for i in its[:3]]
            print(f"{q} -> status {r.status_code}, {len(r.text)} chars, {len(its)} productos (numberOfItems={n}) {names}")
            if its and "url" not in state:
                state["url"] = its[0].get("url")
 
    def t_robots():
        r = get(f"{base}/robots.txt")
        print(f"status {r.status_code}")
        print(r.text[:1800])
        state["sitemaps"] = re.findall(r"(?im)^sitemap:\s*(\S+)", r.text)
 
    def t_sitemap():
        sm = state.get("sitemaps") or [f"{base}/sitemap.xml"]
        print("sitemaps:", sm[:6])
        r = get(sm[0])
        locs = re.findall(r"<loc>(.*?)</loc>", r.text)
        kind = "sitemapindex" if "<sitemapindex" in r.text else "urlset"
        print(f"{sm[0]} -> status {r.status_code}, {kind}, {len(locs)} urls")
        for u in locs[:12]:
            print("  ", u)
        if kind == "sitemapindex" and locs:
            r2 = get(locs[0])
            l2 = re.findall(r"<loc>(.*?)</loc>", r2.text)
            print(f"primer sub-sitemap {locs[0]} -> {r2.status_code}, {len(l2)} urls")
            for u in l2[:12]:
                print("  ", u)
 
    def t_home():
        r = get(base + "/")
        hrefs = re.findall(r'href="(/[^"#?]*)"', r.text)
        uniq = list(dict.fromkeys(hrefs))
        print(f"status {r.status_code}, {len(r.text)} chars, {len(uniq)} enlaces internos únicos")
        cats = [h for h in uniq if h.count("/") == 1 and len(h) > 2 and not h.endswith("/p")]
        print("enlaces de 1 nivel (posibles categorías):", cats[:50])
        state["cat"] = cats[0] if cats else None
 
    def t_cat():
        c = state.get("cat")
        if not c:
            print("sin categoría candidata")
            return
        for q in (c, c + "?page=2"):
            r = get(base + q)
            its, n = items(r.text)
            print(f"{q} -> status {r.status_code}, {len(its)} productos (numberOfItems={n}) {[i.get('name') for i in its[:2]]}")
 
    def t_product():
        u = state.get("url")
        if not u:
            print("sin URL de producto")
            return
        r = get(u)
        print(f"{u} -> status {r.status_code}, {len(r.text)} chars")
        for d in jsonld(r.text):
            print("JSON-LD:", json.dumps(d, ensure_ascii=False)[:900])
        print("¿contiene 'gtin' / 'ean'?:", bool(re.search(r"gtin|\bean\b", r.text, re.I)))
        for m in list(re.finditer(r'"(?:ean|gtin\d*|sku|productId|skuId)"\s*:\s*"?([\w-]+)', r.text))[:6]:
            print("  ", m.group(0)[:80])
 
    step("1) Búsqueda y paginación", t_search)
    step("2) robots.txt", t_robots)
    step("3) sitemap", t_sitemap)
    step("4) Portada (categorías)", t_home)
    step("5) Página de categoría", t_cat)
    step("6) Ficha de un producto", t_product)
 
 
if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in SITES:
        sys.exit(__doc__)
    main(sys.argv[1])
