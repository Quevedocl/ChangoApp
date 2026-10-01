-- ChangoApp · migración 001 (idempotente: se puede ejecutar más de una vez).
-- Pégala completa en Supabase > SQL Editor > Run.
-- Agrega: emparejamiento de productos entre súper, precio por unidad, categorías,
-- búsqueda rápida sin acentos y las funciones que usa la web.

create extension if not exists pg_trgm with schema extensions;
create extension if not exists unaccent with schema extensions;

-- ---------- columnas nuevas ----------
alter table public.products
  add column if not exists match_key text,
  add column if not exists name_key text,
  add column if not exists category text,
  add column if not exists search_text text;

alter table public.store_products
  add column if not exists match_key text,
  add column if not exists name_key text,
  add column if not exists size_text text,
  add column if not exists unit_price numeric(12,2),
  add column if not exists unit_label text;

create unique index if not exists products_match_key_uq on public.products (match_key);
create index if not exists products_name_key_idx on public.products (name_key);
create index if not exists products_category_idx on public.products (category);
create index if not exists products_search_trgm on public.products using gin (search_text extensions.gin_trgm_ops);
create index if not exists products_brand_trgm on public.products using gin (brand extensions.gin_trgm_ops);
create index if not exists sp_store_stock_idx on public.store_products (supermarket_id, in_stock);
create index if not exists sp_match_key_idx on public.store_products (match_key) where product_id is null;
create index if not exists sp_offer_idx on public.store_products (product_id) where is_offer and in_stock;

-- Rellena el texto de búsqueda de productos que ya existían (demo)
update public.products
   set search_text = lower(extensions.unaccent(coalesce(brand, '') || ' ' || name))
 where search_text is null;

-- ---------- une productos de distintos súper ----------
-- 1) por clave exacta (EAN o marca+nombre+tamaño), 2) por nombre normalizado si uno de los
-- súper no trae EAN, 3) crea el producto que falte y lo enlaza.
create or replace function public.link_products() returns void
language plpgsql
set search_path = public, extensions
as $$
begin
  update store_products sp set product_id = p.id
    from products p
   where sp.product_id is null and sp.match_key is not null and sp.match_key = p.match_key;

  update store_products sp set product_id = m.id
    from (select distinct on (name_key) name_key, id from products
           where name_key is not null order by name_key, id) m
   where sp.product_id is null and sp.name_key is not null and sp.name_key = m.name_key;

  insert into products (match_key, name_key, name, brand, size, ean, image_url, category, search_text)
    select distinct on (match_key) match_key, name_key, name, brand, size_text, ean, image_url, category,
           lower(unaccent(coalesce(brand, '') || ' ' || name))
      from store_products
     where product_id is null and match_key is not null
     order by match_key, (image_url is not null) desc, length(name)
  on conflict do nothing;

  update store_products sp set product_id = p.id
    from products p
   where sp.product_id is null and sp.match_key = p.match_key;
end $$;
revoke execute on function public.link_products() from public, anon, authenticated;

-- nombre anterior, por compatibilidad
create or replace function public.link_by_ean() returns void
language sql set search_path = public as $$ select public.link_products(); $$;
revoke execute on function public.link_by_ean() from public, anon, authenticated;

-- ---------- búsqueda para la web ----------
-- q: texto (todas las palabras deben aparecer, sin importar acentos ni orden)
-- cat: categoría · only_offers: solo ofertas · sort: rel | ahorro | unidad | az
-- ids: traer productos específicos (la lista de compras) · lim/off: paginación
create or replace function public.search_products(
  q text default '', cat text default null, only_offers boolean default false,
  sort text default 'rel', ids bigint[] default null, lim int default 24, off int default 0)
returns table (id bigint, name text, brand text, size text, image_url text, category text,
               total bigint, prices jsonb)
language plpgsql stable
set search_path = public, extensions
as $$
#variable_conflict use_column
declare
  qn text := trim(regexp_replace(lower(unaccent(coalesce(q, ''))), '[^a-z0-9 ]', ' ', 'g'));
  toks text[];
  pats text[];
begin
  toks := array(select t from unnest(string_to_array(qn, ' ')) t where t <> '');
  pats := array(select '%' || t || '%' from unnest(toks) t);
  lim := least(greatest(lim, 1), 100);
  off := greatest(off, 0);
  return query
  with base as (
    select p.id, p.name, p.brand, p.size, p.image_url, p.category, p.search_text,
           agg.prices, agg.n, agg.spread, agg.min_unit
      from products p
      cross join lateral (
        select jsonb_agg(jsonb_build_object(
                 's', s.name, 'price', sp.current_price, 'orig', sp.original_price,
                 'offer', sp.is_offer, 'url', sp.external_url, 'at', sp.updated_at,
                 'u', sp.unit_price, 'ul', sp.unit_label) order by sp.current_price) as prices,
               count(*)::int as n,
               max(sp.current_price) - min(sp.current_price) as spread,
               min(sp.unit_price) as min_unit,
               bool_or(sp.is_offer and sp.original_price > sp.current_price) as has_offer
          from store_products sp
          join supermarkets s on s.id = sp.supermarket_id
         where sp.product_id = p.id and sp.in_stock
      ) agg
     where agg.n > 0
       and (ids is null or p.id = any(ids))
       and (cat is null or p.category = cat)
       and (cardinality(pats) = 0 or (p.search_text like pats[1] and p.search_text like all (pats)))
       and (not only_offers or agg.has_offer)
  )
  select b.id, b.name, b.brand, b.size, b.image_url, b.category,
         count(*) over () as total, b.prices
    from base b
   order by case when sort = 'ahorro' then b.spread end desc nulls last,
            case when sort = 'unidad' then b.min_unit end asc nulls last,
            case when sort = 'az' then b.name end asc,
            b.n desc,
            case when cardinality(toks) > 0 then similarity(b.search_text, qn) end desc nulls last,
            b.name
   limit lim offset off;
end $$;
grant execute on function public.search_products(text, text, boolean, text, bigint[], int, int) to anon, authenticated;

-- categorías y marcas disponibles (para los filtros de la web)
create or replace function public.catalog_facets() returns jsonb
language sql stable
set search_path = public
as $$
  with live as (
    select p.category, p.brand from products p
     where exists (select 1 from store_products sp where sp.product_id = p.id and sp.in_stock)
  )
  select jsonb_build_object(
    'categories', coalesce((select jsonb_agg(jsonb_build_object('c', category, 'n', n) order by n desc)
                              from (select category, count(*) n from live where category is not null group by 1) x), '[]'::jsonb),
    'brands', coalesce((select jsonb_agg(jsonb_build_object('b', brand, 'n', n) order by n desc)
                          from (select brand, count(*) n from live
                                 where brand is not null and brand <> '' group by 1 order by n desc limit 40) y), '[]'::jsonb));
$$;
grant execute on function public.catalog_facets() to anon, authenticated;
