"""Publica las últimas líneas de scrape.log como anotación del job (visible en la pestaña del run y por API)."""
import os

path = "scrape.log"
txt = open(path, errors="replace").read() if os.path.exists(path) else "(sin log)"
tail = "\n".join(txt.strip().splitlines()[-30:])[:3800]
tail = tail.replace("%", "%25").replace("\r", "").replace("\n", "%0A")
print(f"::notice title=Resumen {os.environ.get('CHAIN', '')}::{tail}")
