# Supabase security migration 0003

## Scope
This migration tightens database-side mutation boundaries after migrations 0001 and 0002.

- Prevents authenticated users from changing their own profile role or identity.
- Restricts merchant delivery edits to destination details on unassigned records.
- Restricts operators to lifecycle updates on deliveries assigned to their operator profile.
- Limits merchant visibility of operator records to available operators (plus own/admin records).
- Keeps delivery events append-only for authenticated clients.
- Pins SECURITY DEFINER helper search paths and restricts helper execution to authenticated users.

## Important limitations
- This is a database migration, not a live Supabase deployment.
- The Next.js app still uses browser localStorage for its demo workspace; this migration does not make records persistent or cross-device.
- The current UI's delivery status model does not yet map cleanly to every database enum value (notably accepted and picked_up). Complete the application adapter before enabling operator mutations.
- This migration does not implement OTP issuance, hashing, expiry, SMS delivery, or POD verification.
- The trigger permits trusted service-role/background mutations when auth.uid() is null. Never expose the service-role key to the browser.
- Apply to a disposable Supabase project first and run the authorization matrix below before any production use.

## Required verification matrix
Use distinct authenticated test users and an operator row for the operator user.

| Actor | Attempt | Expected |
|---|---|---|
| Merchant A | Update own unassigned destination | Allow |
| Merchant A | Update own delivery status | Deny |
| Merchant A | Change own delivery operator_id | Deny |
| Merchant A | Update Merchant B delivery | Deny |
| Merchant A | Change own profile role to admin | Deny |
| Merchant A | Read unavailable operator | Deny |
| Merchant A | Read available operator | Allow |
| Operator A | Update status on assigned delivery through allowed transition | Allow |
| Operator A | Update another operator's delivery | Deny |
| Operator A | Change recipient/address/merchant/operator fields | Deny |
| Operator A | Skip lifecycle state | Deny |
| Operator A | Append event to assigned delivery with own actor_id | Allow |
| Operator A | Append event using another actor_id | Deny |
| Anonymous | Read or mutate protected records | Deny |

Also verify that no authenticated client can update or delete delivery_events.
