# Academy Outreach

Auditable admissions and candidate-outreach automation. Django owns all
business state and deterministic policy. OpenClaw and real WhatsApp messaging
will only be added after the safety-focused local workflow is stable.

## Current scope: Milestone 1

- Candidate, Campaign, CampaignMember, Message, SystemState, and AuditEvent
- Django Admin as the initial operational interface
- database constraints and controlled message status transitions
- SQLite migrations and model tests

CSV import, queue processing, FakeSender, OpenClaw, WhatsApp, and
ActiveCampaign are intentionally outside this milestone.

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

## Verification

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test
```

## Planned sequence

1. Business core (current milestone)
2. CSV import and candidate normalization
3. Database queue and deterministic safety policies
4. FakeSender
5. OpenClaw message generation
6. Real WhatsApp integration
7. ActiveCampaign integration
