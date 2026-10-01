# Cuánto Sale · Comparador de supermercados (ChangoApp)

Archivos
- index.html  → la web completa, ya conectada a Supabase (proyecto ChangoApp). Ábrela con doble clic o súbela a Vercel/Netlify.
- schema.sql  → respaldo del esquema (ya aplicado en ChangoApp).
- scrape.py   → scraper VTEX (Jumbo, Santa Isabel) que llena la base.
- .github/workflows/scrape.yml → actualización nocturna con GitHub Actions.

Datos de ejemplo
La base trae 14 productos demo (external_id empieza con "demo-"). Para borrarlos, ejecuta en el SQL Editor:
  delete from store_products where external_id like 'demo-%';
  delete from products where not exists (select 1 from store_products sp where sp.product_id = products.id);
Si corres el scraper de Jumbo, los demo de Jumbo quedan sin stock automáticamente y dejan de mostrarse.

Poner en marcha el scraper
1. pip install -r requirements.txt
2. export SUPABASE_URL=... SUPABASE_SERVICE_KEY=...   (ver .env.example)
3. python scrape.py probe jumbo     # verifica que la web expone el catálogo
4. python scrape.py run jumbo       # carga todo el catálogo

Actualización nocturna
Sube la carpeta a GitHub y crea los secrets SUPABASE_URL y SUPABASE_SERVICE_KEY (Settings > Secrets and variables > Actions).

Seguridad
- La clave anon en index.html es pública por diseño; la base solo permite lectura gracias a RLS.
- La service key NUNCA va en index.html ni en el repositorio: solo en el scraper / secrets.
