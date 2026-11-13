-- PostcodeLink Nigeria MVP starter schema
-- Apply only after creating a Supabase project and reviewing the access policies.
create extension if not exists pgcrypto;

create type public.app_role as enum ('merchant', 'operator', 'admin');
create type public.delivery_status as enum (
  'draft', 'pending_assignment', 'assigned', 'accepted',
  'picked_up', 'in_transit', 'delivered', 'failed', 'cancelled'
);

create table public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  full_name text not null,
  role public.app_role not null default 'merchant',
  phone text,
  created_at timestamptz not null default now()
);

create table public.operators (
  id uuid primary key default gen_random_uuid(),
  profile_id uuid not null unique references public.profiles(id) on delete cascade,
  business_name text not null,
  service_areas text[] not null default '{}',
  is_available boolean not null default false,
  created_at timestamptz not null default now()
);

create table public.deliveries (
  id uuid primary key default gen_random_uuid(),
  reference text not null unique,
  merchant_id uuid not null references public.profiles(id),
  operator_id uuid references public.operators(id),
  recipient_name text not null,
  recipient_phone text,
  destination_address text not null,
  destination_area text,
  destination_city text,
  destination_state text,
  postcode_input text,
  postcode_status text not null default 'unverified'
    check (postcode_status in ('unverified','verified','unavailable','invalid')),
  status public.delivery_status not null default 'pending_assignment',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.delivery_events (
  id uuid primary key default gen_random_uuid(),
  delivery_id uuid not null references public.deliveries(id) on delete cascade,
  actor_id uuid references public.profiles(id),
  status public.delivery_status not null,
  note text,
  occurred_at timestamptz not null default now()
);

create index deliveries_merchant_created_idx
  on public.deliveries (merchant_id, created_at desc);
create index deliveries_operator_created_idx
  on public.deliveries (operator_id, created_at desc);
create index delivery_events_delivery_time_idx
  on public.delivery_events (delivery_id, occurred_at desc);

alter table public.profiles enable row level security;
alter table public.operators enable row level security;
alter table public.deliveries enable row level security;
alter table public.delivery_events enable row level security;

-- Intentionally no permissive policies are added here.
-- Add and test role-aware policies before exposing these tables to clients.
