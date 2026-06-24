# CloseOut — Org Structure, Roles & EOD Submission (Cursor build prompt)

Add the company org backbone to the existing Django CloseOut app. The AI brain-dump and EOD generation already exist — **do not rebuild them.** This change adds departments, a 3-tier role model, a real "Post" (submit) action, and a role-scoped oversight dashboard. Match existing code conventions and the existing design system.

## The model we're building toward

**Everyone keeps their personal workspace** (the existing `index.html` — daily log, drafts, progress, wins). That is each person's own dashboard; don't build a second one.

**Oversight is one dashboard, scoped by role:**
- **Employee** → personal workspace only. No oversight view.
- **Manager** (one per board) → the drill-down dashboard **locked to their own board** — they see their team's posted EODs, nothing from other boards.
- **Boss** (single admin) → the full dashboard: picks any board → sees its people → reads their EODs.

Same page, same code — **the server decides what data loads based on the viewer's role.** Never rely on the front-end to hide data.

**Privacy: PRIVATE.** An employee sees only their own EOD. Only their Manager and the Boss can see a person's posted EOD. Employees cannot see each other's EODs.

Flow: employee fills their day → AI cleans messy input into an EOD (already built) → hits **Post** → that posted EOD appears to their Manager and the Boss.

---

## 1. Data model changes (`myApp/models.py`)

**New `Department` model** (we call them "Boards" in the UI)
- `name` (CharField, unique)
- `__str__` returns name

**`UserProfile` changes**
- Replace free-text `department` with `department = ForeignKey(Department, null=True, blank=True, on_delete=SET_NULL)`
- Add `role = CharField(choices=[('EMPLOYEE','Employee'),('MANAGER','Manager'),('BOSS','Boss')], default='EMPLOYEE')`
- Boss may have `department = null`. Each board has exactly one person with role `MANAGER`.
- Keep existing `is_manager` checks working, but prefer migrating callers to `role`.

**`EODReport` changes**
- Add `status = CharField(choices=[('DRAFT','Draft'),('SUBMITTED','Submitted')], default='DRAFT')`
- Add `submitted_at = DateTimeField(null=True, blank=True)`

Data is minimal (pilot) — a plain migration is fine; drop any old text department values and re-assign in admin. Register `Department` in `admin.py`; make `department` + `role` editable on the user/profile admin.

**Seed the 7 boards** via a data migration or a management command (`python manage.py seed_departments`):
Copy Writing Board, Design Board, Development Board, AI Dev Board, Social Media Board, CRM Board, SEO/GEO Board.

---

## 2. Submit / Post flow

- Add **`POST /api/eod/submit/`**: generates (or reuses today's generated) report for the current user + date, saves to `EODReport` with `status='SUBMITTED'`, `submitted_at=now()`. Idempotent — re-posting the same day updates that day's report.
- On `index.html`, add a **Post EOD** action (e.g. in the report modal after Generate): calls submit → toast "Posted".
- Only `SUBMITTED` reports appear in any oversight view. Drafts never leak.

---

## 3. Oversight dashboard (`/dashboard/`) — role-scoped drill-down

Access: roles `MANAGER` and `BOSS` only. Employees get 403.

**Scope by role, server-side:**
- `BOSS` → all departments.
- `MANAGER` → auto-locked to their own `department`; they never see the department picker for other boards, and direct URL access to another board's data returns 403.

Levels, with a date selector (default today, allow past dates):

1. **Boards** (boss only) — list departments with a count: "Design Board · 6 people · 4 posted today". Managers skip this and land straight in their own board.
2. **People in board** — each row: name, **role badge** (Manager / Employee), posted-status for the date (✓ Posted / Pending). Manager pinned to top.
3. **Person's EOD** (for the selected date):
   - the posted **EOD report** text (AI-written),
   - **Working on** — their `IN_PROGRESS` tasks,
   - **Blocked** — blocked tasks + blocker/age,
   - **Tasks done** — their `DONE` tasks, collapsible (optional detail).

---

## 4. Fix styling at the root (shared layout)

The dashboard renders unstyled because all tokens/base CSS live inside `index.html`'s `<style>`.

- Create **`myApp/templates/base.html`** with: the theme bootstrap `<script>`, Google Fonts links, the full `:root` / `[data-theme="dark"]` / `[data-theme="light"]` token blocks, and base styles (`body`, `.nav`, `.btn*`, `.panel`, `.bento`, `.badge`, modal, toast). Expose `{% block head %}` and `{% block content %}`.
- Refactor `index.html`, `dashboard.html`, `login.html` to `{% extends "base.html" %}`, keeping only page-specific markup/styles.
- Dashboard then inherits the exact employee-page look. Reuse `.panel` for sections, `.badge` for role/status pills, `.bento` for board counts, existing chip styles for Blocked/Tomorrow.

---

## Guardrails
- CSRF on all POSTs (follow existing `X-CSRFToken` pattern).
- Migrations checked in. ORM only.
- Don't touch AI services except to let "Post" persist the generated report.
- Don't break the theme toggle or existing employee flow.
- Enforce privacy + scope in the **view/queryset**, not the template.
- Edge cases: board with nobody posted, person with no EOD for the date, manager with an empty board, boss with no departments seeded.

## Definition of done
- Employee: personal workspace + can Post.
- Manager: opens dashboard → sees only their own board's people → reads their posted EODs (+ working-on, blocked, done).
- Boss: picks any board → people → posted EODs.
- Employees cannot see each other's EODs.
- Dashboard visually matches the employee page (shared `base.html`).
- Tell me what you built, what you stubbed, what's left.

**Build order: models + migration + seed the 7 boards → submit endpoint → `base.html` refactor → role-scoped dashboard. Stop after the models so I can confirm the schema before any UI.**
