# CloseOut — Pilot Setup for a 4-Person Team (Cursor build prompt)

We're piloting with 4 real users (the superadmin will create them manually in Django admin). This build makes sure the app cleanly supports that structure and is easy to verify. Match existing conventions; don't rebuild AI generation or the core flows.

## The pilot org (one reporting line, one board)
```
Boss → Lead (Senior AI dev, manages the board) → [AI dev, Graphic designer]
```
| Person | role | department |
|---|---|---|
| Boss | BOSS | (blank) |
| Lead (Senior AI dev) | MANAGER | Core Team |
| AI dev | EMPLOYEE | Core Team |
| Graphic designer | EMPLOYEE | Core Team |

Both reports sit on **one board** so the manager can oversee both. (Their jobs differ — AI dev / designer — but that's not a role or a board; it's just what they do.)

## What to make sure works (mostly verification + admin polish)

### 1. Admin must make this assignable in a few clicks
- In Django admin, `UserProfile` (or the user admin) must expose **`role`** (Employee / Manager / Boss) and **`department`** (FK dropdown) as editable fields, ideally inline on the user page.
- Departments are selectable from existing records. Ensure a **"Core Team"** department exists — seed it via a small idempotent data migration or `python manage.py ensure_department "Core Team"`. Do NOT seed the other 6 boards (they'd show as empty cards).
- The boss/superadmin can set all 4 users' role + department without touching code.

### 2. Don't show empty boards
- The boss dashboard should list **only departments that have at least one member** (or only non-empty boards), so the pilot doesn't render 6 dead "0 people" cards.

### 3. Visibility must match the hierarchy (enforce in the view/queryset)
- **Employee** (AI dev, designer) → personal workspace only; 403 on the dashboard; sees only their own EOD.
- **Manager** (Lead) → dashboard scoped to **Core Team only**; sees both reports' posted EODs **and** posts her own (managers are not exempt from posting). 403 on any other board's data.
- **Boss** → sees everyone across all (non-empty) boards, including the Lead's own EOD; can read each posted EOD; can assign tasks (existing feature).
- Privacy stays PRIVATE: the two employees cannot see each other's EODs.

### 4. Self-check command (so the superadmin can confirm setup without guessing)
- Add `python manage.py check_pilot` that prints each user with their role, department, and whether they posted today — so after creating the 4 users the admin can instantly verify roles/boards are correct. Read-only; creates nothing.

## Out of scope
No new users created in code (admin does that manually). No multi-board managers. No new features.

## Definition of done
- "Core Team" department exists; admin can set role + department per user easily.
- Dashboard hides empty boards.
- Scoping verified: employee = self, manager = Core Team only, boss = all.
- `check_pilot` prints the 4 users' role/department/posted-today.

## Verification round-trip (run with the 4 real accounts)
1. AI dev: fill buckets → Generate & Post today → "Posted ✓".
2. Lead (manager): dashboard shows **both** reports under Core Team; AI dev = Posted; EOD readable; designer visible too.
3. Boss: sees Lead + both reports; reads each posted EOD.
4. Boss: assign a task to the designer → it lands in the designer's log badged "From boss".
Run it; don't assume it.
