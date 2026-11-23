# Creator Campaign Tracker

An admin-first tool for running influencer marketing campaigns: a brand books
creators onto a campaign, tracks each booking through a status workflow from
invite to payout, and stays inside a fixed budget and creator cap. Built on
Django's admin, backed by managed Postgres and S3-compatible object storage,
with a Groq-powered help assistant embedded in the admin.

- **Live URL:** _<fill in after deploy>_ — `/admin/` for staff, `/accounts/login/` for everyone
- **Demo logins** (seeded): `admin_demo`, `manager_demo`, `reviewer_demo` — password `demo-pass-1234`

## Why this domain

The take-home offered three stock domains. I picked a close cousin of the actual
job — influencer campaign management — because it carries the same shape the brief
asks for (a many-to-many with real attributes on the join, a status workflow, a
file upload) while mirroring the day-to-day of the role. It is deliberately the
same size as the suggested domains, not larger.

The four models:

| Model | Role | Notable relationships |
|-------|------|-----------------------|
| `Creator` | An influencer | has many `SocialAccount`; optional one-to-one to a portal `User` |
| `SocialAccount` | One platform presence | **FK** to `Creator`; computed `engagement_rate` |
| `Campaign` | A brand's booking round | **M2M** to `Creator` *through* `Participation`; `banner` image |
| `Participation` | One creator's booking | FK to both; the status workflow, money, and `deliverable` file live here |

## Why this stack

- **Django 5 + the built-in admin.** The brief is essentially a list of things
  Django's admin does well: generated admin, `list_filter`/`search_fields`,
  inlines, custom actions, permissions that gate the UI, `help_text` on fields.
  Choosing Django means the evaluated surface is real framework customization,
  not a hand-rolled CRUD UI. The job also lists Python and PostgreSQL directly.
- **PostgreSQL on a managed host (Neon).** Relational data with real foreign
  keys and aggregate queries (budget sums, follower totals). SQLite is used for
  local dev only; production uses `DATABASE_URL` and never falls back to a file.
- **Cloudflare R2 for object storage** via `django-storages` — S3-compatible,
  zero-egress-fee free tier. Swapping providers is one endpoint env var.
- **WhiteNoise** for hashed, compressed static files, so no separate CDN is
  needed for the admin's CSS/JS.
- **Groq** for the assistant — free tier, OpenAI-compatible, fast. The client is
  a thin `httpx` wrapper, so pointing at any OpenAI-compatible endpoint is a
  config change.
- **Argon2** as the password hasher.

## Business logic

The core rule lives on `Participation` (in the model, not a view):

- **Status workflow** `invited -> accepted -> submitted -> approved -> paid`, with
  `declined` and `rejected` branches. Illegal jumps (e.g. `invited -> paid`) are
  rejected in `clean()`; `rejected -> submitted` allows a rework loop; `declined`
  and `paid` are terminal. Stage timestamps are stamped automatically on save.
- **Budget guard** — committed fees across a campaign can't exceed its budget.
- **Capacity guard** — active bookings can't exceed `max_creators`.
- **Payment guard** — a creator can't be marked `paid` with a zero fee, and only
  Admin/Manager roles can run the "mark paid" action.
- **Computed fields** — `SocialAccount.engagement_rate`,
  `Campaign.committed_spend` / `budget_remaining` / `is_over_budget`.

Covered by 12 tests in `campaigns/tests.py` (`python manage.py test`).

## Roles

Three roles, enforced through Django groups/permissions (which the admin honours
automatically) plus a few explicit gates. A lower role sees a *visibly* smaller
admin, not just blocked POSTs.

| Capability | Admin | Manager | Reviewer |
|---|:---:|:---:|:---:|
| Campaigns / creators: add, edit, delete | yes | add + edit | view only |
| Participations: triage status | yes | yes | yes |
| Edit `agreed_fee` / run "mark paid" | yes | yes | no |
| Manage users | yes | no | no |

The Reviewer has no "Add campaign" button and gets a 403 on the add URL; the
`agreed_fee` field renders read-only for them; the "mark paid" action is absent
from their action dropdown. (Verified end-to-end during development.)

## Security

- Passwords hashed with **Argon2** (`PASSWORD_HASHERS`).
- **CSRF** on all state-changing requests, including the assistant endpoint
  (the widget sends the token header).
- **Upload validation** — type + size (5 MB) on images and deliverables; the AI
  chat input is length-capped and server-validated.
- **No secrets in the repo** — everything is read from env via `django-environ`;
  `.env` is gitignored and `.env.example` documents the keys.
- **Production hardening** when `DEBUG=False`: SSL redirect, HSTS, secure +
  HTTP-only cookies, `nosniff`, `X-Frame-Options: DENY`, 8-hour session expiry.
- `python manage.py check --deploy` is clean.

## AI help assistant

A chat bubble in the admin answers "what does this field mean / how do I fill
this out". It is **grounded**: `assistant/context.py` introspects the live model
fields — verbose names, `help_text`, choices, required-ness — and feeds only that
into the system prompt, scoped to whichever model the admin page is editing. The
model is told to answer from the reference or admit it doesn't know. If the API
key is missing, the call times out, or the provider errors, the widget shows a
plain message and the admin keeps working — the assistant never takes the page
down. Input is length-capped and the API key is a secret, never logged.

## Running locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # then set SECRET_KEY; defaults use SQLite + no S3
python manage.py migrate
python manage.py seed         # demo users + realistic data
python manage.py runserver
```

Visit `http://127.0.0.1:8000/admin/` and sign in with a demo login above. To try
the assistant locally, put a free Groq key in `.env` as `GROQ_API_KEY`.

Reset the data at any time with `python manage.py seed` (add `--creators N
--campaigns N` to change the scale).

## Deployment (Render + Neon + Cloudflare R2)

1. Create a Neon Postgres database; copy its `DATABASE_URL`.
2. Create a Cloudflare R2 bucket and an S3 API token.
3. On Render, create a web service from this repo (`render.yaml` is included).
   Set `DEBUG=False`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, `DATABASE_URL`,
   the `USE_S3` + `AWS_*` storage vars, and `GROQ_API_KEY`.
4. `build.sh` runs `collectstatic` and `migrate`. Run `python manage.py seed`
   once from the Render shell to create demo data and logins.

Static files are served by WhiteNoise; uploads go straight to R2, never to the
instance disk.

## What I deliberately skipped, and why

- **OAuth login (bonus).** Local auth already satisfies "real authentication".
  Google/GitHub OAuth drops in via `django-allauth`, but it adds a provider
  dependency and a "what role does a new OAuth user get" policy question I didn't
  want to answer casually for a demo. Noted as the first thing I'd add.
- **A full creator-facing portal.** The job describes a dual-sided product; this
  task grades the admin. I built a minimal read-only portal (a creator sees their
  own campaigns and earnings) to show the seam, and stopped there rather than
  reimplementing campaign management for creators.
- **Live metric scraping.** The job mentions scraping Instagram/YouTube/etc. The
  schema models the *output* of that (per-account follower/engagement metrics
  with a `last_synced` stamp), but the ingestion pipeline is out of scope for a
  take-home and would be a separate worker service.
- **Conversation memory in the assistant.** Each question is answered
  independently against the field context. Multi-turn memory wasn't worth the
  state for a field-help tool.

## What I'd do differently with more time

- Add OAuth with an explicit, safe default role (Reviewer) for new users.
- Move the budget/capacity checks into a `select_for_update` transaction so two
  concurrent bookings can't both pass the Python-level check.
- A model-level transition API (django-fsm style) instead of hand-checking the
  transition map in `clean()`.
- Signed, time-limited URLs for private deliverables instead of public-read.
- Thumbnails for avatars/banners generated on upload.
