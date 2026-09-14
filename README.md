# Academy Outreach

Auditable admissions and candidate-outreach automation. Django owns all
business state and deterministic policy. OpenClaw and real WhatsApp messaging
will only be added after the safety-focused local workflow is stable.

## Current scope: Milestones 1–2

- Candidate, Campaign, CampaignMember, Message, SystemState, and AuditEvent
- Django Admin as the initial operational interface
- database constraints and controlled message status transitions
- SQLite migrations and model tests
- CSV candidate import with E.164 phone normalization
- duplicate, invalid-record, and do-not-contact reporting
- controlled campaign membership creation with audit events

Queue processing, FakeSender, OpenClaw, WhatsApp, and ActiveCampaign are
intentionally outside the current scope.

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

## Verification

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test
```

## Planned sequence

1. Business core (complete)
2. CSV import and candidate normalization (complete)
3. Database queue and deterministic safety policies (next)
4. FakeSender
5. OpenClaw message generation
6. Real WhatsApp integration
7. ActiveCampaign integration
