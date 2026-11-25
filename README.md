# Creator Campaign Tracker

A small tool for running influencer campaigns. A brand books creators onto a
campaign, each booking moves through a status workflow from invite to payout, and
the campaign has to stay inside its budget and creator cap. It's built on Django's
admin, with Postgres and file storage on Neon and a Groq-backed help assistant in
the admin.

- **Live URL:** https://creator-campaign-admin.onrender.com (`/admin/` for staff, `/accounts/login/` for everyone else)
- **Demo logins:** `admin_demo`, `manager_demo`, `reviewer_demo`, password `demo-pass-1234`

It's on Render's free tier, so the first request after it's been idle takes ~30-60s
to wake up.

## The domain

I went with influencer campaign management instead of one of the three suggested
domains because it's the same size and shape but closer to the actual job. It still
has everything the brief asks for: a many-to-many with real fields on the join
table, a status workflow, and a file upload.

Four models:

| Model | What it is | Relationships |
|-------|------------|---------------|
| `Creator` | An influencer | has many `SocialAccount`; optional link to a portal `User` |
| `SocialAccount` | One platform account | FK to `Creator`; computed `engagement_rate` |
| `Campaign` | A brand's campaign | M2M to `Creator` through `Participation`; banner image |
| `Participation` | One creator on one campaign | FK to both; holds the status workflow, the fee, and a deliverable file |

## Why Django

The brief is basically a list of things Django's admin already does well: a
generated admin, list filters and search, inlines, custom actions, permissions
that actually gate the UI, help_text on fields. Using Django means what gets
reviewed is real admin customization instead of a CRUD UI I hand-built. Python and
Postgres are also both in the job description.

The rest:

- **Postgres on Neon** for the real relationships and the aggregate queries (budget
  totals, follower counts). SQLite is only for local dev; production reads
  `DATABASE_URL` and refuses to boot on SQLite.
- **Neon Object Storage** for uploads, through django-storages. It's S3-compatible
  and lives on the same Neon account as the database, so one provider covers both.
  It's a plain S3 backend, so moving to R2 or S3 is just env vars.
- **WhiteNoise** for static files so I don't need a separate CDN for the admin assets.
- **Groq** for the assistant: free, OpenAI-compatible, fast. The client is a thin
  httpx wrapper around the chat endpoint.
- **Argon2** for password hashing.

## Business logic

The real logic sits on `Participation`, in the model rather than a view:

- The status workflow is `invited -> accepted -> submitted -> approved -> paid`,
  plus `declined` and `rejected` branches. Illegal jumps like `invited -> paid` are
  rejected in `clean()`. `rejected -> submitted` lets a creator rework and resubmit.
  `declined` and `paid` are terminal. Timestamps for each stage are set on save.
- Committed fees across a campaign can't go over its budget.
- Active bookings can't go over `max_creators`.
- You can't mark someone paid with a zero fee, and only Admin/Manager can run the
  pay action.
- Computed fields: `engagement_rate` on an account, and `committed_spend`,
  `budget_remaining`, `is_over_budget` on a campaign.

There are 14 tests in `campaigns/tests.py` covering the transitions, the budget and
capacity rules, the payment gate, and the engagement calc. Run them with
`python manage.py test`.

## Roles

Three roles. Permissions come from Django groups, which the admin respects on its
own, plus a few explicit checks. A lower role sees a smaller admin, not just a
blocked request.

| | Admin | Manager | Reviewer |
|---|:---:|:---:|:---:|
| Campaigns / creators: add, edit, delete | yes | add + edit | view only |
| Participations: change status | yes | yes | yes |
| Edit fee / mark paid | yes | yes | no |
| Manage users | yes | no | no |

As a Reviewer there's no "Add campaign" button, the add URL returns 403, the
`agreed_fee` field is read-only, "Paid" isn't in the status dropdown, and the mark
paid action isn't in the list.

## Security

- Passwords hashed with Argon2.
- CSRF on everything that changes state, including the assistant endpoint.
- Upload validation: file type and 5 MB size limit on images and deliverables, and
  the chat input is length-capped and validated server-side.
- No secrets in the repo. Everything comes from env vars; `.env` is gitignored and
  `.env.example` lists the keys.
- With `DEBUG=False`: SSL redirect, HSTS, secure and HTTP-only cookies, nosniff,
  `X-Frame-Options: DENY`, and an 8-hour session. `manage.py check --deploy` is clean.

## The help assistant

There's a chat bubble in the admin that answers "what does this field mean / how do
I fill this out". It's grounded: `assistant/context.py` reads the actual model
fields (verbose name, help_text, choices, required) and that's all that goes into
the prompt, scoped to whichever model you're editing. The prompt tells the model to
answer from that reference or say it doesn't know. If the key is missing, the call
times out, or the API errors, the widget shows a short message and the admin keeps
working. The input is length-capped and the key is only ever an env var.

## Running locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # set SECRET_KEY; defaults use SQLite and local file storage
python manage.py migrate
python manage.py seed
python manage.py runserver
```

Then open `http://127.0.0.1:8000/admin/` and log in with one of the demo users. For
the assistant to work locally, add a Groq key as `GROQ_API_KEY` in `.env`.

Re-run `python manage.py seed` any time to reset the data (`--creators N` and
`--campaigns N` change the scale).

## Deploying

It deploys as a Render Blueprint (`render.yaml`):

1. Create a Neon project. Use the pooled `DATABASE_URL`, and in the same project
   turn on Object Storage, make a public-read bucket, and create an S3 credential.
2. On Render pick New -> Blueprint and point it at the repo. It reads `render.yaml`
   and asks for the secret env vars: `DATABASE_URL`, the `AWS_*` storage values,
   `AWS_S3_CUSTOM_DOMAIN` (`<endpoint-host>/<bucket>`), `GROQ_API_KEY`, and the host
   for `ALLOWED_HOSTS` / `CSRF_TRUSTED_ORIGINS`. `DEBUG=False`, `USE_S3=True`, the
   region, and path-style addressing come from the blueprint.
3. `build.sh` runs collectstatic and migrate on deploy. Run `python manage.py seed`
   once against the Neon database to create the demo data.

Static files go through WhiteNoise; uploads go straight to Neon storage, never the
instance disk.

## What I left out

- **OAuth.** Local auth already covers "real authentication". OAuth is easy to add
  with django-allauth, but it brings a provider dependency and the question of what
  role a brand-new OAuth user should get, which I didn't want to hand-wave for a
  demo. It'd be the first thing I add.
- **A full creator portal.** The job is a two-sided product but this task is about
  the admin, so I built a small read-only portal (a creator can see their own
  campaigns and earnings) to show the seam and left it there.
- **Metric scraping.** The job mentions scraping the platforms. I modelled the
  output of that (per-account follower/engagement numbers with a `last_synced`
  field) but the scraping itself is a separate service, out of scope here.
- **Chat history.** Each question is answered on its own against the field context.
  Multi-turn memory wasn't worth it for a field-help tool.

## With more time

- OAuth with a safe default role (Reviewer) for new sign-ups.
- Put the budget and capacity checks in a `select_for_update` transaction so two
  bookings at once can't both slip past the Python check.
- A proper transition API (something like django-fsm) instead of the hand-written
  map in `clean()`.
- Signed, expiring URLs for private deliverables instead of public-read.
- Generating thumbnails for avatars and banners on upload.
