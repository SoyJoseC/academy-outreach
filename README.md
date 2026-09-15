# Academy Outreach

Auditable admissions and candidate-outreach automation. Django owns all
business state and deterministic policy. OpenClaw and real WhatsApp messaging
will only be added after the safety-focused local workflow is stable.

## Current scope: Milestones 1–4

- Candidate, Campaign, CampaignMember, Message, SystemState, and AuditEvent
- Django Admin as the initial operational interface
- database constraints and controlled message status transitions
- SQLite migrations and model tests
- CSV candidate import with E.164 phone normalization
- duplicate, invalid-record, and do-not-contact reporting
- controlled campaign membership creation with audit events
- database-backed outbound queue with idempotency protection
- deterministic pause, campaign, opt-out, human-review, interval, hourly,
  and daily policy checks
- a worker command using `FakeSender` by default
- deterministic opt-out detection and audit history
- validated `send`, `human_review`, and `skip` admissions-agent decisions
- an OpenClaw `/v1/responses` client using a required structured tool call
- campaign-specific human escalation visible in Django Admin
- an OpenClaw admissions Skill and placeholder-only academy knowledge base

Real WhatsApp, inbound webhooks, and ActiveCampaign are intentionally outside
the current scope.

## Local setup

```bash
python -m venv .venv
source .venv/bin/activate  # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Open `http://127.0.0.1:8000/admin/` after creating the superuser.
The project loads local values from `.env`; that file is ignored by Git.

See [`docs/architecture.md`](docs/architecture.md) for the model boundaries and
safety decisions introduced in this milestone.

## Import candidates

Create the campaign in Django Admin, then prepare a UTF-8 CSV containing:

```csv
first_name,last_name,phone,email,country,course_interest
```

Run:

```bash
python manage.py import_candidates candidates.csv --campaign 1
```

Local phone numbers use `DEFAULT_PHONE_REGION` from `.env` (`VC` by default).
Prefer international numbers beginning with `+`. The command reports imported,
updated, skipped, duplicate, invalid, and do-not-contact rows. It never sends
messages.

## Run the safe message worker

Activate a campaign and ensure its imported candidates are `READY`, then run a
single safe iteration:

```bash
python manage.py run_message_worker --once
```

Run continuously with the default five-second polling interval:

```bash
python manage.py run_message_worker
```

The worker creates one idempotent initial message per campaign member, applies
all deterministic policies, and uses `FakeSender`. Its provider IDs start with
`fake-`; no external messaging service is contacted. Set
`SystemState.outbound_enabled` to false in Django Admin to stop outbound
processing immediately.

## Configure OpenClaw message generation

The safe default is `TemplateAdmissionsAgent`, so a fresh installation remains
fully local. To use a separately configured OpenClaw Gateway, enable its
OpenResponses endpoint and set:

```env
ADMISSIONS_AGENT_BACKEND=agents.services.OpenClawAdmissionsAgent
OPENCLAW_ENDPOINT=http://127.0.0.1:18789
OPENCLAW_AUTH_TOKEN=replace-with-gateway-token
OPENCLAW_AGENT_ID=academy-admissions
OPENCLAW_MODEL=openclaw/academy-admissions
```

The client calls `POST /v1/responses` and requires exactly one validated
`admissions_decision` function call. Malformed, incomplete, or failed responses
mark the message as failed and never reach the sender. Keep the Gateway on
loopback, a tailnet, or another private ingress: its HTTP bearer credential has
operator-level authority.

The Skill is at
`openclaw/workspace/skills/academy-admissions/SKILL.md`. The files under
`knowledge/` intentionally contain no academy facts yet. Replace their TODO
sections only with information approved by the academy.

## Verification

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test
```

## Planned sequence

1. Business core (complete)
2. CSV import and candidate normalization (complete)
3. Database queue, deterministic safety policies, and FakeSender (complete)
4. OpenClaw structured message generation and human escalation (complete)
5. Real WhatsApp and authenticated inbound integration (next)
6. ActiveCampaign integration
