
"""Descubre cómo entrega los productos la web de un supermercado (usa un navegador real).
 
Uso:  python discover.py jumbo
Abre la web, busca "leche" y muestra: (1) todas las llamadas de red al propio sitio,
(2) las llamadas JSON, y (3) los datos de productos incrustados en la página.
"""
import re
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
IGNORE = ("google", "facebook", "doubleclick", "newrelic", "hotjar", "clarity", "segment", "sentry",
          "tiktok", "criteo", "onetrust", "cookielaw", "analytics", "gtm", "adobe", "amplitude", "braze",
          "cloudflareinsights", "snapchat", "pinterest", "maze.co", "mimolive", "creativecdn", "adnxs",
          "on.aws", "run.app")
STATIC = (".png", ".jpg", ".jpeg", ".webp", ".svg", ".gif", ".css", ".woff", ".woff2", ".ico", ".mp4")
 
 
def main(slug):
    reqs, jsons = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(locale="es-CL", user_agent=UA, viewport={"width": 1366, "height": 900})
        page = ctx.new_page()
 
        def on_request(r):
            u = r.url.lower()
            if any(x in u for x in IGNORE) or u.split("?")[0].endswith(STATIC) or u.startswith("data:"):
                return
            if r.resource_type in ("xhr", "fetch", "document"):
                reqs.append((r.method, r.resource_type, r.url[:300]))
 
        def on_response(r):
            try:
                if r.request.resource_type not in ("xhr", "fetch"):
                    return
                if any(x in r.url.lower() for x in IGNORE) or "json" not in r.headers.get("content-type", ""):
                    return
                h = {k: v[:60] for k, v in r.request.headers.items()
                     if k.lower().startswith("x-") or k.lower() in ("authorization", "content-type")}
                jsons.append((r.request.method, r.status, r.url[:300], h, (r.request.post_data or "")[:300],
                              r.text()[:400].replace("\n", " ")))
            except Exception:
                pass
 
        page.on("request", on_request)
        page.on("response", on_response)
        try:
            page.goto(SITES[slug], wait_until="domcontentloaded", timeout=45000)
        except Exception as e:
            print("Aviso al abrir:", repr(e)[:150])
        page.wait_for_timeout(6000)
        page.mouse.wheel(0, 3000)
        page.wait_for_timeout(4000)
        html = page.content()
        print(f"Título: {page.title()!r} | URL final: {page.url} | HTML: {len(html)} caracteres")
        browser.close()
 
    print("\n=== 1) LLAMADAS DE RED (xhr/fetch/document) ===")
    seen = set()
    for m, t, u in reqs:
        if u not in seen:
            seen.add(u)
            print(f"{m} [{t}] {u}")
        if len(seen) >= 50:
            break
 
    print("\n=== 2) LLAMADAS JSON ===")
    for m, s, u, h, post, body in jsons[:10]:
        print(f"{m} {s} {u}\n  headers: {h}\n  enviado: {post}\n  respuesta: {body}")
 
    print("\n=== 3) DATOS INCRUSTADOS EN EL HTML ===")
    scripts = re.findall(r"<script([^>]*)>(.*?)</script>", html, flags=re.S)
    for attrs, body in scripts:
        if len(body) > 2000:
            print(f"script grande: attrs={attrs.strip()[:120]!r} largo={len(body)} inicio={body[:150]!r}")
    for attrs, body in scripts:
        m = re.search(r'"(?:productName|skuName|displayName|brand|listPrice|sellingPrice|price)"', body)
        if m and len(body) > 2000:
            i = m.start()
            print(f"\n--- fragmento con precios (attrs={attrs.strip()[:80]!r}) ---\n{body[max(0, i - 300):i + 900]}")
            break
    else:
        print("No encontré precios dentro de los <script> del HTML.")
        i = html.find("$")
        print("Texto de la página cerca de un precio:", re.sub(r"\s+", " ", html[max(0, i - 200):i + 200]) if i > 0 else "(sin $)")
 
 
if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in SITES:
        sys.exit(__doc__ + "\nSitios: " + ", ".join(SITES))
    main(sys.argv[1])
