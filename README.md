# ChangoApp · Comparador de supermercados

Compara precios de supermercados chilenos (Jumbo y Santa Isabel; más cadenas experimentales), arma tu lista y ve dónde sale más barato.

## Archivos
- `index.html` → la web completa (conectada a Supabase). Ábrela con doble clic o súbela a Vercel/Netlify/GitHub Pages.
- `migracion_001.sql` y luego `migracion_002.sql` → **ejecútalas en ese orden** en Supabase (SQL Editor). Son idempotentes. La 002 arregla las imágenes.
- `limpiar_demo.sql` → borra los productos de ejemplo (ejecútalo después de la primera carga real).
- `schema.sql` → esquema completo, solo para una base nueva.
- `scrape.py` → scraper (buscador interno de cada súper, sin navegador) y carga Supabase.
- `.github/workflows/scrape.yml` → actualización nocturna (06:00 UTC) o manual con modo `test`/`run`.
- `.github/workflows/probar.yml` → prueba rápida de todos los súper.
- `explore.py` / `discover.py` + sus workflows → herramientas para investigar sitios nuevos.

## Puesta en marcha
1. En Supabase > SQL Editor, pega y ejecuta `migracion_001.sql` y después `migracion_002.sql`.
2. En GitHub > Settings > Secrets and variables > Actions crea `SUPABASE_URL` y `SUPABASE_SERVICE_KEY`.
3. Actions > "Probar supermercados" para verificar que los sitios responden.
4. Actions > "Actualizar precios" > Run workflow con modo `run` (la primera carga demora; luego es nocturna). **Mientras no termine esa carga solo verás los productos demo.**
5. Cuando termine con éxito, ejecuta `limpiar_demo.sql` en Supabase.

En tu computador:
```
pip install -r requirements.txt
export SUPABASE_URL=... SUPABASE_SERVICE_KEY=...    # ver .env.example
python scrape.py test jumbo      # no guarda nada
python scrape.py run jumbo
```

## Qué súper hay y por qué
| Cadena | Estado | Cómo se lee |
|---|---|---|
| Jumbo | activa | buscador interno (Constructor.io), todas las categorías |
| Santa Isabel | activa | igual que Jumbo |
| Alvi, Telemercados | **experimental** | API pública de VTEX (esquema documentado). Alvi es mayorista: algunos precios dependen del volumen |
| A Cuenta, Central Mayorista | **experimental** | HTML de la búsqueda (Next.js / React Flight) |
| Tottus | **experimental** | HTML de la búsqueda (`__NEXT_DATA__`); puede tener antibot |
| Unimarc | **experimental** | puede requerir IP residencial; probablemente solo funcione desde tu computador |
| Líder | **experimental** | protegida por antibot (PerimeterX); lo más probable es que falle |

"Experimental" = escrita sin poder probarla contra el sitio real. Corre `python scrape.py test <cadena>`
(o el workflow "Probar supermercados") y mira la línea `RESULTADO`. Si una cadena da `NO FUNCIONA`, no guarda
nada ni daña los datos de las demás. Para investigarla usa el workflow "Descubrir APIs".

Los precios que se guardan son los del catálogo nacional; pueden variar por sucursal.

## Cómo se unen los productos entre súper
Cada producto recibe una clave: su EAN si la web lo entrega; si no, marca + nombre normalizado
(sin acentos ni orden de palabras) + tamaño. Misma clave = mismo producto, y la web muestra ambos precios.
Los productos que solo existen en un súper también aparecen (con un solo precio).

## Variedad de catálogo
`scrape.py` recorre todas las categorías de cada súper (decenas de miles de productos) y además ~670 términos y marcas como red de seguridad. Para ampliar, agrega términos separados
por coma en `GROUPS` o `BRANDS`. Los términos de varias palabras ("papel higienico") se buscan completos.

## Protecciones
- Si una corrida trae menos del 60% de lo anterior (bloqueo o corrida parcial), **no** marca productos sin stock y falla visiblemente.
- 30 fallos seguidos cortan el recorrido y guardan lo recolectado.
- Las IPs de GitHub Actions a veces reciben 403 de sitios con anti-bot; si pasa seguido, corre el scraper desde tu computador.

## Datos de ejemplo
Para borrar los productos demo:
```sql
delete from store_products where external_id like 'demo-%';
delete from products where not exists (select 1 from store_products sp where sp.product_id = products.id);
```

## Seguridad
La clave `anon` en `index.html` es pública por diseño (RLS solo permite lectura). La service key
**nunca** va en `index.html` ni en el repositorio: solo en secrets o en tu `.env` local.

## Pendiente conocido
Las cadenas experimentales hay que verificarlas una por una (ver tabla).
