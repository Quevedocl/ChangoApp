# ChangoApp · Comparador de supermercados

Compara precios de Jumbo y Santa Isabel, arma tu lista y ve dónde sale más barato.

## Archivos
- `index.html` → la web completa (conectada a Supabase). Ábrela con doble clic o súbela a Vercel/Netlify/GitHub Pages.
- `migracion_001.sql` → **ejecútala una vez** en Supabase (SQL Editor). Es idempotente.
- `schema.sql` → esquema completo, solo para una base nueva.
- `scrape.py` → scraper (lee el JSON-LD de las búsquedas, sin navegador) y carga Supabase.
- `.github/workflows/scrape.yml` → actualización nocturna (06:00 UTC) o manual con modo `test`/`run`.
- `.github/workflows/probar.yml` → prueba rápida de todos los súper.
- `explore.py` / `discover.py` + sus workflows → herramientas para investigar sitios nuevos.

## Puesta en marcha
1. En Supabase > SQL Editor, pega y ejecuta `migracion_001.sql`.
2. En GitHub > Settings > Secrets and variables > Actions crea `SUPABASE_URL` y `SUPABASE_SERVICE_KEY`.
3. Actions > "Probar supermercados" para verificar que los sitios responden.
4. Actions > "Actualizar precios" > Run workflow con modo `run` (la primera carga demora; luego es nocturna).

En tu computador:
```
pip install -r requirements.txt
export SUPABASE_URL=... SUPABASE_SERVICE_KEY=...    # ver .env.example
python scrape.py test jumbo      # no guarda nada
python scrape.py run jumbo
```

## Cómo se unen los productos entre súper
Cada producto recibe una clave: su EAN si la web lo entrega; si no, marca + nombre normalizado
(sin acentos ni orden de palabras) + tamaño. Misma clave = mismo producto, y la web muestra ambos precios.
Los productos que solo existen en un súper también aparecen (con un solo precio).

## Variedad de catálogo
`scrape.py` recorre ~670 términos: 14 categorías y ~200 marcas. Para ampliar, agrega términos separados
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
Unimarc, Líder, Tottus y A Cuenta no están activos: sus webs no entregan JSON-LD como Jumbo/Santa Isabel.
Usa el workflow "Descubrir APIs" para investigar cada uno antes de agregarlo a `CHAINS`.
