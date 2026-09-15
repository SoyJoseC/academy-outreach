# OpenClaw WhatsApp activation runbook

This runbook turns the tested local workflow into initial WhatsApp outreach.
Do not activate it until the academy has approved the contact list, message
content, operating hours, and opt-out handling process.

## 1. Keep outbound paused

In Django Admin, open **System state** and disable outbound processing. Keep
the worker stopped while configuring OpenClaw.

## 2. Install and configure OpenClaw

Install OpenClaw on the same private host as Django, or make it reachable over
a tailnet/private tunnel. The safest simple layout is the Gateway bound to
loopback on its default port `18789`.

Complete OpenClaw onboarding, ensure token authentication is configured, and
enable its OpenResponses endpoint:

```bash
openclaw onboard
openclaw config set gateway.http.endpoints.responses.enabled true
openclaw gateway install
openclaw gateway status
```

Retrieve the configured Gateway token in an interactive terminal:

```bash
openclaw gateway auth-token --show
```

Treat this token as an operator credential. Never commit it or expose the
Gateway directly to the public Internet.

## 3. Link the academy WhatsApp account

Run this on the Gateway host and scan the QR code with the phone that owns the
academy WhatsApp account:

```bash
openclaw channels login --channel whatsapp --account default
openclaw channels status --probe
```

The account must have an active listener. A linked account without a running
Gateway cannot send.

## 4. Install the admissions workspace

Make the repository's `openclaw/workspace/skills/academy-admissions` directory
available in the configured OpenClaw workspace. Replace the TODO content under
`knowledge/` only with academy-approved facts. Prices, dates, schedules, and
policies that have not been approved must remain absent so the agent escalates
instead of inventing them.

## 5. Configure Django safely

Start with `FakeSender`:

```env
ADMISSIONS_AGENT_BACKEND=agents.services.OpenClawAdmissionsAgent
MESSAGE_SENDER_BACKEND=messaging.sender.FakeSender
OPENCLAW_ENDPOINT=http://127.0.0.1:18789
OPENCLAW_AUTH_TOKEN=replace-with-the-real-gateway-token
OPENCLAW_AGENT_ID=academy-admissions
OPENCLAW_MODEL=openclaw/academy-admissions
OPENCLAW_WHATSAPP_ACCOUNT_ID=default
```

Apply checks:

```bash
python manage.py check
python manage.py migrate
python manage.py check_openclaw --health-only
python manage.py check_openclaw
python manage.py test
```

Run one campaign through `FakeSender` and review the generated message and
audit history in Django Admin.

## 6. Enable the real sender

Pause outbound again, stop the worker, and change only:

```env
MESSAGE_SENDER_BACKEND=messaging.sender.OpenClawWhatsAppSender
```

Restart Django and the worker. Import a very small academy-approved test CSV,
activate that test campaign, then enable outbound in **System state**:

```bash
python manage.py run_message_worker --once
```

Confirm the message appeared in WhatsApp and that Django stored a non-empty
provider message ID. Only then start continuous processing:

```bash
python manage.py run_message_worker
```

## 7. Daily operation

1. Create a campaign in Django Admin.
2. Keep it in Draft while importing the CSV.
3. Review invalid, duplicate, skipped, and do-not-contact rows.
4. Set conservative hourly and daily limits.
5. Activate the campaign.
6. Confirm the worker and OpenClaw Gateway are running.
7. Monitor message history and human-review items in Django Admin.
8. Pause **System state** immediately if behavior is unexpected.

The current milestone sends one initial outbound message per campaign member.
Inbound replies are still monitored in WhatsApp and must be reflected manually
in Django Admin. Automatic inbound reply and opt-out ingestion is the next
milestone; until it is complete, an operator must promptly mark opt-outs as
`do_not_contact`.
