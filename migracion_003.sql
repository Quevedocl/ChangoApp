-- ChangoApp · migración 003 (idempotente). Ejecútala DESPUÉS de migracion_002.sql.
-- 1) Un solo precio por supermercado en cada ficha ("Más comparables" cuenta cadenas, no filas).
-- 2) Separa los packs (Pack 6 / 12 / 18) que estaban unidos y corrige el precio por litro/kg.
-- 3) Da más tiempo a link_products para que no se corte con muchos productos.

alter function public.link_products() set statement_timeout = '900s';

-- 2) packs ya cargados: "Pack 6 un. ... 80 ml" tenía clave 1x80ml y precio por litro de 1 sola unidad
with fix as (
  select id, (regexp_match(name, '(?:^|[^[:alnum:]_.])(\d{1,3})\s*(?:unidades|unidad|unid|und|uds?|un)(?![[:alpha:]])', 'i'))[1]::int as pack
    from store_products
   where name_key ~ '\|1x[0-9.]+(g|ml)$'
)
update store_products sp set
  name_key   = replace(sp.name_key, '|1x', '|' || f.pack || 'x'),
  match_key  = case when sp.match_key like 'nk:%' then replace(sp.match_key, '|1x', '|' || f.pack || 'x') else sp.match_key end,
  product_id = case when sp.match_key like 'nk:%' then null else sp.product_id end,
  size_text  = f.pack || ' × ' || sp.size_text,
  unit_price = round(sp.unit_price / f.pack, 1)
  from fix f
 where f.id = sp.id and f.pack between 2 and 200 and sp.size_text is not null and sp.size_text not like '%×%';

select public.link_products();

-- fichas que quedaron sin ningún precio asociado (las viejas mezcladas)
delete from products p
 where not exists (select 1 from store_products sp where sp.product_id = p.id);

-- 1) search_products con un precio por supermercado
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
                 's', c.sname, 'price', c.current_price, 'orig', c.original_price,
                 'offer', c.is_offer, 'url', c.external_url, 'at', c.updated_at,
                 'u', c.unit_price, 'ul', c.unit_label) order by c.current_price) as prices,
               count(*)::int as n,
               max(c.current_price) - min(c.current_price) as spread,
               min(c.unit_price) as min_unit,
               bool_or(c.is_offer and c.original_price > c.current_price) as has_offer,
               (array_agg(c.image_url order by c.current_price) filter (where c.image_url is not null))[1] as img
          from (
            -- un solo precio por supermercado: el más barato con stock
            select distinct on (sp.supermarket_id) sp.*, s.name as sname
              from store_products sp
              join supermarkets s on s.id = sp.supermarket_id
             where sp.product_id = p.id and sp.in_stock
             order by sp.supermarket_id, sp.current_price, sp.updated_at desc
          ) c
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

notify pgrst, 'reload schema';
