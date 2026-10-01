-- ChangoApp · migración 002 (idempotente). Ejecútala DESPUÉS de migracion_001.sql.
-- Arregla las imágenes: si un producto no tiene foto propia, usa la de cualquiera de sus súper,
-- y rellena las fotos que faltaban en productos ya existentes.

-- 1) link_products ahora también completa products.image_url desde store_products
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

  -- NUEVO: productos sin foto la toman de alguno de sus súper
  update products p set image_url = x.image_url
    from (select distinct on (product_id) product_id, image_url
            from store_products
           where product_id is not null and image_url is not null
           order by product_id, in_stock desc, updated_at desc) x
   where p.id = x.product_id and p.image_url is null;
end $$;
revoke execute on function public.link_products() from public, anon, authenticated;

-- 2) search_products devuelve siempre una imagen si existe en algún súper
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
           agg.prices, agg.n, agg.spread, agg.min_unit, agg.img
      from products p
      cross join lateral (
        select jsonb_agg(jsonb_build_object(
                 's', s.name, 'price', sp.current_price, 'orig', sp.original_price,
                 'offer', sp.is_offer, 'url', sp.external_url, 'at', sp.updated_at,
                 'u', sp.unit_price, 'ul', sp.unit_label) order by sp.current_price) as prices,
               count(*)::int as n,
               max(sp.current_price) - min(sp.current_price) as spread,
               min(sp.unit_price) as min_unit,
               bool_or(sp.is_offer and sp.original_price > sp.current_price) as has_offer,
               (array_agg(sp.image_url order by sp.current_price) filter (where sp.image_url is not null))[1] as img
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
  select b.id, b.name, b.brand, b.size, coalesce(b.image_url, b.img) as image_url, b.category,
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

-- 3) rellena de una vez las fotos de lo que ya está cargado
select public.link_products();

notify pgrst, 'reload schema';
