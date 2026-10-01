"""Descubre qué APIs internas usa la web de un supermercado (usa un navegador real).
 
Uso:  python discover.py jumbo
Abre la web, hace una búsqueda de "leche" y muestra las llamadas JSON que hace la propia página.
"""
import sys
 
from playwright.sync_api import sync_playwright
 
SITES = {
    "jumbo": "https://www.jumbo.cl/busqueda?ft=leche",
    "santa-isabel": "https://www.santaisabel.cl/busqueda?ft=leche",
    "tottus": "https://www.tottus.cl/",
    "acuenta": "https://www.acuenta.cl/",
    "unimarc": "https://www.unimarc.cl/",
    "lider": "https://super.lider.cl/",
}
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
IGNORE = ("google", "facebook", "doubleclick", "newrelic", "hotjar", "clarity", "segment",
          "sentry", "tiktok", "criteo", "onetrust", "cookielaw", "analytics", "gtm", "adobe",
          "amplitude", "braze", "cloudflareinsights", "snapchat", "pinterest")
KEYS = ("catalog", "search", "plp", "product", "graphql", "bff", "api", "browse", "query")
 
 
def run(slug):
    found = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(locale="es-CL", user_agent=UA, viewport={"width": 1366, "height": 900})
        page = ctx.new_page()
 
        def on_response(r):
            try:
                req = r.request
                if req.resource_type not in ("xhr", "fetch"):
                    return
                if any(x in r.url.lower() for x in IGNORE):
                    return
                if "json" not in r.headers.get("content-type", ""):
                    return
                headers = {k: v[:80] for k, v in req.headers.items()
                           if k.lower() not in ("cookie", "user-agent", "accept-language", "sec-ch-ua",
                                                "sec-ch-ua-mobile", "sec-ch-ua-platform", "referer", "origin")}
                found.append({"m": req.method, "url": r.url, "status": r.status, "headers": headers,
                              "post": (req.post_data or "")[:500], "body": r.text()[:600]})
            except Exception:
                pass
 
        page.on("response", on_response)
        try:
            page.goto(SITES[slug], wait_until="domcontentloaded", timeout=45000)
        except Exception as e:
            print("Aviso al abrir:", repr(e)[:150])
        page.wait_for_timeout(6000)
        try:
            box = page.locator('input[type="search"], input[placeholder*="uscar"], input[name*="search"]').first
            box.fill("leche", timeout=5000)
            box.press("Enter")
        except Exception:
            print("(no encontré el buscador; solo se muestran las llamadas de la portada)")
        page.wait_for_timeout(8000)
        print(f"Título de la página: {page.title()!r} | URL final: {page.url}")
        browser.close()
 
    found.sort(key=lambda f: -sum(k in f["url"].lower() for k in KEYS))
    print(f"\nLlamadas JSON encontradas: {len(found)} (se muestran las 12 más relevantes)\n")
    for f in found[:12]:
        print("-" * 70)
        print(f"{f['m']} {f['status']} {f['url'][:400]}")
        print("headers:", f["headers"])
        if f["post"]:
            print("body enviado:", f["post"])
        print("respuesta:", f["body"].replace("\n", " ")[:600])
 
 
if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in SITES:
        sys.exit(__doc__ + "\nSitios: " + ", ".join(SITES))
    run(sys.argv[1])
 
