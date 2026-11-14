-- PostcodeLink Reliability Gate: Supabase mutation hardening
-- Apply after 0001_initial_schema.sql and 0002_role_based_rls_policies.sql.
-- This migration does not provision auth users or connect the Next.js app.

-- Use SECURITY DEFINER only for narrowly scoped identity helpers. Pin search_path
-- to prevent object-shadowing attacks.
create or replace function public.current_user_role()
returns public.app_role
language sql
stable
security definer
set search_path = ''
as $$
  select p.role
  from public.profiles as p
  where p.id = (select auth.uid())
  limit 1;
$$;

create or replace function public.is_admin()
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1
    from public.profiles as p
    where p.id = (select auth.uid())
      and p.role = 'admin'::public.app_role
  );
$$;

revoke all on function public.current_user_role() from public, anon;
revoke all on function public.is_admin() from public, anon;
grant execute on function public.current_user_role() to authenticated;
grant execute on function public.is_admin() to authenticated;

-- A user may edit their own profile details, but cannot promote themselves,
-- change their identity key, or alter their role. Admin role changes remain
-- possible through a trusted service/admin path.
create or replace function public.guard_profile_mutation()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  if auth.uid() is not null and not public.is_admin() then
    if new.id is distinct from old.id
       or new.role is distinct from old.role then
      raise exception 'Profile identity and role are managed by administrators'
        using errcode = '42501';
    end if;
  end if;
  return new;
end;
$$;

drop trigger if exists profiles_guard_mutation on public.profiles;
create trigger profiles_guard_mutation
before update on public.profiles
for each row execute function public.guard_profile_mutation();

-- Enforce field-level mutation rules even if a client has broad UPDATE grants.
-- Merchants can edit destination details only while a delivery is still
-- unassigned. Operators can advance only the delivery lifecycle for jobs
-- assigned to their operator profile. Admin/service operations are separate.
create or replace function public.guard_delivery_mutation()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_role public.app_role;
  v_operator_id uuid;
begin
  if auth.uid() is null then
    -- Service-role/background operations are not subject to end-user RLS.
    return new;
  end if;

  v_role := public.current_user_role();

  if v_role = 'admin'::public.app_role then
    return new;
  end if;

  if v_role = 'merchant'::public.app_role then
    if old.merchant_id is distinct from auth.uid()
       or new.merchant_id is distinct from old.merchant_id
       or new.operator_id is distinct from old.operator_id
       or new.reference is distinct from old.reference
       or new.status is distinct from old.status
       or old.status not in (
         'draft'::public.delivery_status,
         'pending_assignment'::public.delivery_status
       ) then
      raise exception 'Merchant may edit destination details only before assignment'
        using errcode = '42501';
    end if;

    if new.id is distinct from old.id
       or new.created_at is distinct from old.created_at then
      raise exception 'Delivery identity fields are immutable'
        using errcode = '42501';
    end if;

    return new;
  end if;

  if v_role = 'operator'::public.app_role then
    select o.id into v_operator_id
    from public.operators as o
    where o.profile_id = auth.uid()
    limit 1;

    if v_operator_id is null or old.operator_id is distinct from v_operator_id
       or new.operator_id is distinct from old.operator_id
       or new.merchant_id is distinct from old.merchant_id
       or new.reference is distinct from old.reference
       or new.recipient_name is distinct from old.recipient_name
       or new.recipient_phone is distinct from old.recipient_phone
       or new.destination_address is distinct from old.destination_address
       or new.destination_area is distinct from old.destination_area
       or new.destination_city is distinct from old.destination_city
       or new.destination_state is distinct from old.destination_state
       or new.postcode_input is distinct from old.postcode_input
       or new.postcode_status is distinct from old.postcode_status
       or new.created_at is distinct from old.created_at then
      raise exception 'Operator may update only an assigned delivery status'
        using errcode = '42501';
    end if;

    if new.status is distinct from old.status and not (
      (old.status = 'assigned' and new.status in ('accepted','picked_up','failed'))
      or (old.status = 'accepted' and new.status in ('picked_up','failed'))
      or (old.status = 'picked_up' and new.status in ('in_transit','failed'))
      or (old.status = 'in_transit' and new.status in ('delivered','failed'))
    ) then
      raise exception 'Invalid operator delivery status transition'
        using errcode = '23514';
    end if;

    return new;
  end if;

  raise exception 'No permission to update delivery'
    using errcode = '42501';
end;
$$;

drop trigger if exists deliveries_guard_mutation on public.deliveries;
create trigger deliveries_guard_mutation
before update on public.deliveries
for each row execute function public.guard_delivery_mutation();

-- Replace overly broad legacy policies with role-scoped policies.
drop policy if exists "Users can update their own profile" on public.profiles;
drop policy if exists "Admins can manage all profiles" on public.profiles;
drop policy if exists "Operators can view their own profile" on public.operators;
drop policy if exists "Merchants can view active operators for dispatch" on public.operators;
drop policy if exists "Operators can update their availability and service areas" on public.operators;
drop policy if exists "Merchants can update their own deliveries before pickup" on public.deliveries;
drop policy if exists "Operators can update status on assigned deliveries" on public.deliveries;
drop policy if exists "Actors can append delivery events" on public.delivery_events;

create policy "Profile owner or admin can update profile"
on public.profiles for update
to authenticated
using (id = (select auth.uid()) or public.is_admin())
with check (id = (select auth.uid()) or public.is_admin());

create policy "Operators and admins can view operator records"
on public.operators for select
to authenticated
using (
  profile_id = (select auth.uid())
  or public.is_admin()
  or (
    public.current_user_role() = 'merchant'::public.app_role
    and is_available = true
  )
);

create policy "Operators update own availability"
on public.operators for update
to authenticated
using (profile_id = (select auth.uid()) or public.is_admin())
with check (profile_id = (select auth.uid()) or public.is_admin());

create policy "Merchants update own unassigned deliveries"
on public.deliveries for update
to authenticated
using (
  merchant_id = (select auth.uid())
  and status in ('draft'::public.delivery_status, 'pending_assignment'::public.delivery_status)
)
with check (
  merchant_id = (select auth.uid())
  and status in ('draft'::public.delivery_status, 'pending_assignment'::public.delivery_status)
);

create policy "Assigned operators update assigned delivery status"
on public.deliveries for update
to authenticated
using (
  operator_id in (
    select o.id from public.operators as o
    where o.profile_id = (select auth.uid())
  )
)
with check (
  operator_id in (
    select o.id from public.operators as o
    where o.profile_id = (select auth.uid())
  )
);

create policy "Authenticated actors append scoped delivery events"
on public.delivery_events for insert
to authenticated
with check (
  actor_id = (select auth.uid())
  and exists (
    select 1
    from public.deliveries as d
    where d.id = delivery_events.delivery_id
      and (
        d.merchant_id = (select auth.uid())
        or d.operator_id in (
          select o.id from public.operators as o
          where o.profile_id = (select auth.uid())
        )
        or public.is_admin()
      )
  )
);

-- Keep audit history append-only for authenticated clients.
drop policy if exists "Actors can append delivery events" on public.delivery_events;
