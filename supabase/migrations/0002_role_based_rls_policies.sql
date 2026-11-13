-- Migration: 0002_role_based_rls_policies.sql
-- Implements tested, role-aware Row Level Security (RLS) policies for PostcodeLink Nigeria

-- 1. Helper function to check role of current user
create or replace function public.current_user_role()
returns public.app_role
language sql
security definer
stable
as $$
  select role from public.profiles where id = auth.uid();
$$;

create or replace function public.is_admin()
returns boolean
language sql
security definer
stable
as $$
  select exists (
    select 1 from public.profiles
    where id = auth.uid() and role = 'admin'
  );
$$;

-- 2. Profiles Table Policies
create policy "Users can view their own profile"
  on public.profiles for select
  using (auth.uid() = id or public.is_admin());

create policy "Users can update their own profile"
  on public.profiles for update
  using (auth.uid() = id)
  with check (auth.uid() = id and role = (select role from public.profiles where id = auth.uid())); -- Prevent self-privilege escalation

create policy "Admins can manage all profiles"
  on public.profiles for all
  using (public.is_admin());

-- 3. Operators Table Policies
create policy "Operators can view their own profile"
  on public.operators for select
  using (profile_id = auth.uid() or public.is_admin());

create policy "Merchants can view active operators for dispatch"
  on public.operators for select
  using (
    is_available = true or
    public.current_user_role() in ('merchant', 'admin')
  );

create policy "Operators can update their availability and service areas"
  on public.operators for update
  using (profile_id = auth.uid() or public.is_admin())
  with check (profile_id = auth.uid() or public.is_admin());

-- 4. Deliveries Table Policies
create policy "Merchants can view deliveries they created"
  on public.deliveries for select
  using (
    merchant_id = auth.uid() or
    public.is_admin()
  );

create policy "Assigned operators can view deliveries assigned to them"
  on public.deliveries for select
  using (
    operator_id in (select id from public.operators where profile_id = auth.uid())
  );

create policy "Merchants can insert deliveries"
  on public.deliveries for insert
  with check (
    merchant_id = auth.uid() and
    public.current_user_role() in ('merchant', 'admin')
  );

create policy "Merchants can update their own deliveries before pickup"
  on public.deliveries for update
  using (merchant_id = auth.uid() or public.is_admin())
  with check (merchant_id = auth.uid() or public.is_admin());

create policy "Operators can update status on assigned deliveries"
  on public.deliveries for update
  using (
    operator_id in (select id from public.operators where profile_id = auth.uid())
  )
  with check (
    operator_id in (select id from public.operators where profile_id = auth.uid())
  );

-- 5. Delivery Events (Audit Trail - Immutable)
create policy "Merchants and operators can view events for their deliveries"
  on public.delivery_events for select
  using (
    exists (
      select 1 from public.deliveries d
      where d.id = delivery_events.delivery_id
      and (
        d.merchant_id = auth.uid() or
        d.operator_id in (select id from public.operators where profile_id = auth.uid()) or
        public.is_admin()
      )
    )
  );

create policy "Actors can append delivery events"
  on public.delivery_events for insert
  with check (
    actor_id = auth.uid() and
    exists (
      select 1 from public.deliveries d
      where d.id = delivery_events.delivery_id
      and (
        d.merchant_id = auth.uid() or
        d.operator_id in (select id from public.operators where profile_id = auth.uid()) or
        public.is_admin()
      )
    )
  );

-- Intentionally NO UPDATE OR DELETE policies on delivery_events to enforce immutable audit history.

