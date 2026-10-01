-- Ya aplicado en el proyecto ChangoApp de Supabase. Guardado aquí como respaldo.
create extension if not exists pg_trgm with schema extensions;

create table public.supermarkets (
  id serial primary key,
  slug text unique not null,
  name text not null,
  logo_url text,
  base_url text not null
);

create table public.products (
  id bigserial primary key,
  name text not null,
  brand text,
  size text,
  ean text unique,
  image_url text,
  created_at timestamptz default now()
);

create table public.store_products (
  id bigserial primary key,
  supermarket_id int not null references public.supermarkets(id),
  product_id bigint references public.products(id),
  external_id text not null,
  name text not null,
  brand text,
  ean text,
  category text,
  external_url text,
  image_url text,
  current_price int not null,
  original_price int,
  is_offer boolean default false,
  in_stock boolean default true,
  updated_at timestamptz default now(),
  unique (supermarket_id, external_id)
);

create table public.price_history (
  id bigserial primary key,
  store_product_id bigint not null references public.store_products(id) on delete cascade,
  price int not null,
  recorded_at timestamptz default now()
);

create table public.shopping_lists (
  id bigserial primary key,
  user_id uuid references auth.users(id) on delete cascade,
  list_name text not null,
  items_json jsonb not null default '[]',
  created_at timestamptz default now()
);

create index on public.store_products (ean);
create index on public.store_products (product_id);
create index on public.store_products using gin (name extensions.gin_trgm_ops);
create index on public.products using gin (name extensions.gin_trgm_ops);
create index on public.price_history (store_product_id, recorded_at desc);

-- Une productos de distintos súper con el mismo EAN (la llama el scraper)
create or replace function public.link_by_ean() returns void
language sql
set search_path = public
as $$
  insert into products (name, brand, ean, image_url)
    select distinct on (ean) name, brand, ean, image_url
    from store_products where ean is not null
    on conflict (ean) do nothing;
  update store_products sp set product_id = p.id
    from products p where sp.ean = p.ean and sp.product_id is null;
$$;
revoke execute on function public.link_by_ean() from public, anon, authenticated;

create view public.product_prices with (security_invoker = true) as
  select p.id as product_id, p.name, p.brand, p.image_url,
         s.name as supermarket, sp.current_price, sp.original_price,
         sp.is_offer, sp.external_url, sp.updated_at
  from public.products p
  join public.store_products sp on sp.product_id = p.id
  join public.supermarkets s on s.id = sp.supermarket_id
  where sp.in_stock;

alter table public.supermarkets enable row level security;
alter table public.products enable row level security;
alter table public.store_products enable row level security;
alter table public.price_history enable row level security;
alter table public.shopping_lists enable row level security;

create policy "lectura publica" on public.supermarkets for select using (true);
create policy "lectura publica" on public.products for select using (true);
create policy "lectura publica" on public.store_products for select using (true);
create policy "lectura publica" on public.price_history for select using (true);
create policy "listas propias" on public.shopping_lists for all
  using (auth.uid() = user_id) with check (auth.uid() = user_id);
