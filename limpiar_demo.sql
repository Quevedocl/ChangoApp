-- Borra los productos de ejemplo (demo). Ejecútalo UNA vez, cuando ya hayas cargado datos reales
-- con el scraper (Actions > "Actualizar precios" > modo run). Solo toca filas con external_id 'demo-%'.
delete from store_products where external_id like 'demo-%';
delete from products where not exists (select 1 from store_products sp where sp.product_id = products.id);
notify pgrst, 'reload schema';
