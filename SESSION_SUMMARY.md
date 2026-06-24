# CloseOut — Session Summary (June 22, 2026)

This document records what was built and updated during today's work on the **CloseOut** EOD (end-of-day) report generator, following the plan in `Closeout cursor prompt.MD`.

---

## Starting point

The app was a Django 5.1.15 project with a single-page UI (`myApp/templates/index.html`) that:

- Let users log tasks and generate EOD reports via OpenAI
- Stored **tasks in `localStorage`** (not the database)
- Used `localStorage` for theme and settings
- Had no authentication, no manager view, and no persistence across devices

---

## Phase 0 — Persistence & accounts

### Finding
Tasks were **localStorage-only**. That blocked roll-over, team features, and search — so database backing was done first.

### What we built

| Area | Change |
|------|--------|
| **Auth** | Django built-in login at `/login/`. Managers identified via a `Managers` group. |
| **Models** | `Task`, `Blocker`, `UserProfile` added in `myApp/models.py` |
| **Migrations** | `0001_initial.py` — core models |
| **Admin** | Models registered in `myApp/admin.py` |
| **localStorage** | Kept **only** for theme preference (`closeout:theme`). All work data moved to the DB. |

### Models (Phase 0)

- **`Task`** — `user`, `date`, `title`, `project`, `status` (DONE / IN_PROGRESS / BLOCKED / TOMORROW), `rolled_from` (idempotent roll-over), timestamps
- **`Blocker`** — `task`, `kind` (BLOCKED / NEEDS_FROM_OTHERS), `unblocker` (User FK), `dependency_text`, `note`, `created_at`
- **`UserProfile`** — `display_name`, `department`, `ai_model`, `style_guide`

### Setup added

- `requirements.txt` — Django 5.1.15, python-dotenv
- `.env.example` — template for `OPENAI_API_KEY`
- `python manage.py setup_managers_group` — creates the Managers group

---

## Phase 1 — Core product features

### 1.1 Cross-day roll-over
- Yesterday's **TOMORROW** tasks automatically become today's **IN_PROGRESS**
- Idempotent via `rolled_from` FK — no duplicate rolls on refresh
- Banner shown when items are rolled forward

### 1.2 Brain dump
- `POST /braindump/` — paste messy notes, AI parses into structured tasks
- User reviews and confirms before bulk save (`POST /api/tasks/bulk/`)

### 1.3 Stale task nudge
- IN_PROGRESS tasks unchanged for 3+ days surface a nudge
- One-click **Mark blocked** action

### 1.4 Blocker system
- On BLOCKED status: attach who/what unblocks (@mention user or free-text dependency)
- Blocker **age** label ("Blocked 3 days")
- **BLOCKED** vs **NEEDS_FROM_OTHERS** distinction
- `notify_unblocker()` stub in `myApp/services/notifications.py` (`# TODO: Slack/email`)

### 1.5 Manager dashboard (`/dashboard/`)
- Permission-gated to **Managers** group (403 for others)
- Four lanes: **Shipped**, **In flight**, **Blocked**, **Needs attention**
- **Blocker heatmap** — grouped by unblocker/dependency
- **Today's wins** — recognition prompt for kudos
- Soft **pending count** ("3 pending") — not punitive
- Optional **AI digest** paragraph

### Phase 1 architecture

| Layer | Files |
|-------|-------|
| Services | `myApp/services/ai.py`, `task_service.py`, `notifications.py` |
| Views / API | `myApp/views.py`, `myApp/urls.py` |
| Templates | `index.html` (refactored to API-backed), `login.html`, `dashboard.html` |
| CSRF | All POST/PATCH/DELETE requests include `X-CSRFToken` |

### API endpoints (Phase 1)

```
GET/POST   /api/tasks/
PATCH/DELETE /api/tasks/<id>/
POST       /api/tasks/<id>/blocker/
DELETE     /api/tasks/<id>/blocker/
POST       /api/tasks/<id>/mark-blocked/
POST       /api/tasks/bulk/
POST       /api/tasks/clear/
POST       /braindump/
POST       /api/generate-eod/
GET        /api/profile/
POST       /api/profile/update/
GET        /api/users/
GET        /dashboard/
```

---

## Phase 2 — Extended generate, insights & search

### 2.1 Generate (extended)
- **Multiple formats** from one log: Plain text, Slack, Manager email
- **Tone** control: Professional, Casual, Concise
- **Length** control: Brief, Standard, Detailed
- Format/tone/length selectable in the report modal; defaults saved in Settings
- Every generated report **saved to `EODReport`** model

### 2.2 Scheduled auto-send
- Per-user settings on `UserProfile`:
  - `timezone`, `auto_send_enabled`, `auto_send_time`
  - `quiet_hours_start`, `quiet_hours_end`
  - `last_auto_send_date` (prevents double-send)
- Management command: `python manage.py send_scheduled_eods`
- Runs within a 15-minute window of the user's configured send time; skips quiet hours
- Actual delivery stubbed via `send_scheduled_eod()` in `notifications.py`

### 2.3 Personal payback
- **Consistency indicator** (private, sidebar) — active days in last 30 vs window; encouraging message only visible to the user
- **Wins archive** — running list of completed tasks
- **Week in review** — AI summary of the last 7 days for 1:1 prep (`POST /api/week-review/`)

### 2.4 Search
- **Personal search** on main page — tasks and past EOD reports (`GET /api/search/?q=...`)
- **Team search** on manager dashboard (`GET /api/search/?team=1&q=...`)
- Managers can open team report previews (`GET /api/reports/<id>/`)

### Phase 2 models & migration

- **`EODReport`** — `user`, `date`, `format`, `tone`, `length`, `content`, `auto_generated`, `created_at`
- **`UserProfile` extended** — timezone, default format/tone/length, auto-send fields
- Migration: `0002_userprofile_auto_send_enabled_and_more.py`

### New API endpoints (Phase 2)

```
GET  /api/insights/consistency/
GET  /api/insights/wins/
POST /api/week-review/
GET  /api/search/
GET  /api/reports/
GET  /api/reports/<id>/
```

### Phase 2 services

- `myApp/services/report_service.py` — save reports, consistency stats, wins archive, week review payload, search, auto-send scheduling
- `myApp/services/ai.py` — extended for formats, tone, length, week review, manager digest

---

## UI / UX updates (across all phases)

- Enterprise-style layout retained; dark/light theme toggle preserved
- Theme stored in `localStorage` with System / Light / Dark options
- Sidebar panels: consistency, week review, wins archive, search
- Report modal: format tabs + tone/length controls
- Settings modal: report defaults, timezone, auto-send schedule, quiet hours
- **Bug fix:** removed duplicate localStorage-based JavaScript in `index.html` that was overriding the API-backed code; app script moved to end of `<body>`

---

## Project structure (after today)

```
eod_generator/
├── .env                    # OPENAI_API_KEY (gitignored)
├── .env.example
├── requirements.txt
├── Closeout cursor prompt.MD
├── SESSION_SUMMARY.md      # this file
├── scripts/
│   └── fix_index_phase2.py # one-time index.html restructure helper
└── myApp/
    ├── models.py           # UserProfile, Task, Blocker, EODReport
    ├── views.py            # Auth, REST API, dashboard
    ├── urls.py
    ├── admin.py
    ├── migrations/
    │   ├── 0001_initial.py
    │   └── 0002_userprofile_auto_send_enabled_and_more.py
    ├── management/commands/
    │   ├── setup_managers_group.py
    │   └── send_scheduled_eods.py
    ├── services/
    │   ├── ai.py
    │   ├── task_service.py
    │   ├── report_service.py
    │   └── notifications.py
    └── templates/
        ├── index.html
        ├── login.html
        └── dashboard.html
```

---

## How to run

```powershell
cd C:\Users\win10\Downloads\eod_generator
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Copy .env.example → .env and set OPENAI_API_KEY

python manage.py migrate
python manage.py createsuperuser
python manage.py setup_managers_group   # add manager users to Managers group in admin
python manage.py runserver
```

- App: http://127.0.0.1:8000/
- Login: http://127.0.0.1:8000/login/
- Dashboard (managers): http://127.0.0.1:8000/dashboard/

### Auto-send (production)

Schedule every 15 minutes:

```powershell
python manage.py send_scheduled_eods
```

Users enable it in **Settings → Enable daily auto-send** and set timezone, send time, and optional quiet hours.

---

## Intentionally stubbed (not wired yet)

| Feature | Location | Notes |
|---------|----------|-------|
| Blocker notifications | `notifications.notify_unblocker()` | `# TODO: Slack/email` |
| Scheduled EOD delivery | `notifications.send_scheduled_eod()` | `# TODO: Slack/email` |

---

## Phase 3 — Not started (backlog per spec)

- External auto-pull integrations (GitHub, Linear/Jira, calendar)
- Trends over time (throughput, recurring blockers, meeting load)
- Auto-generated 1:1 prep from last two weeks of reports

---

## Definition of done checklist

| Phase | Status |
|-------|--------|
| Phase 0 — DB + auth foundation | Done |
| Phase 1 — Roll-over, brain dump, blockers, manager dashboard | Done |
| Phase 2 — Formats, auto-send, insights, search | Done |
| Phase 3 — Integrations & trends | Backlog |

---

## Quick reference — task statuses

| Status | Meaning |
|--------|---------|
| `DONE` | Shipped / completed today |
| `IN_PROGRESS` | Still working on it |
| `BLOCKED` | Stuck — blocker attached |
| `TOMORROW` | Carries to next day's log via roll-over |
