# Project Agent Instructions

## Architecture

- Django is the source of truth for business state and deterministic policy.
- OpenClaw is an external AI and messaging service.
- The LLM may recommend what to say; Django decides whether it may happen.

## Safety

AI output must never bypass the global pause, campaign state, rate limits,
do-not-contact status, duplicate prevention, human-review locks, or validation.

## Development rules

- Use Django and SQLite for the MVP.
- Keep business logic out of views and external-agent prompts.
- Use `TextChoices`, database constraints, and transactions where appropriate.
- Do not add Redis, Celery, React, or PostgreSQL unless requested.
- Never commit credentials or invent academy information.
- Run `python manage.py check` and all tests after significant changes.
- Do not proceed while checks or tests fail.
- Use `FakeSender` before any real messaging integration.
- Never enable real WhatsApp without explicit authorization.

## Required implementation order

1. Django business core, models, Admin, migrations, and model tests.
2. CSV import and normalization.
3. Database-backed queue and deterministic policies.
4. `FakeSender`.
5. OpenClaw integration and knowledge base.
6. Real WhatsApp integration.
7. ActiveCampaign integration.

