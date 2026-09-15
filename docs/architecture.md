# Milestones 1–5 architecture

## Responsibility boundaries

- `candidates` owns person-level admissions and contact eligibility data.
- `campaigns` owns campaigns and candidate participation within each campaign.
- `messaging` owns auditable message state and the global automation switch.
- `agents` owns AI request/response validation and the OpenClaw boundary.
- `audit` owns immutable operational event records.

Campaign-specific fields live on `CampaignMember`, not `Candidate`, so one
candidate can participate independently in multiple campaigns.

## Safety decisions

- Setting `Candidate.do_not_contact` forces the candidate status to
  `DO_NOT_CONTACT` at the model boundary.
- `SystemState` is a database singleton with primary key `1`; its initial row is
  created by a data migration.
- Message status changes use an explicit transition map. Invalid transitions
  raise `ValidationError`.
- A message validates that its candidate and campaign match its
  `CampaignMember`.
- Important uniqueness and ordering rules are enforced by database constraints,
  not only Admin forms.
- Audit events are read-only in Django Admin.
- Candidate phone numbers are stored in E.164 form and nonblank phones/emails
  are unique at the database layer.
- Each CSV row is processed in its own transaction so one invalid row does not
  discard other valid candidates.
- Importing creates campaign memberships but never creates or sends messages.
- Initial outbound messages use a database-unique idempotency key.
- Django checks global pause, campaign state and dates, do-not-contact,
  human-review locks, candidate validity, minimum interval, and hourly/daily
  limits before claiming a message and immediately before sending it.
- `FakeSender` is the only enabled sender; real WhatsApp deliberately raises an
  error if invoked.
- Sender confirmation updates message, member, candidate, and audit history in
  a transaction.
- Opt-out recognition is deterministic and globally updates the candidate.
- Pending messages pass a deterministic policy check before candidate data is
  sent to any agent and another final check before `FakeSender` is called.
- OpenClaw receives a structured admissions payload through its documented
  `/v1/responses` endpoint. A required function call limits output to `send`,
  `human_review`, or `skip`, and Django validates the response again.
- Human review sets both the message state and the campaign-specific member
  lock. Malformed agent output fails closed and creates an agent-error audit
  event.
- The configured agent recommends content only. It never receives authority to
  change or bypass deterministic Django policy.
- OpenClaw endpoints require a bearer token. Plain HTTP is rejected for public
  hosts and allowed only for loopback/private network addresses.
- Real outbound sends use OpenClaw's documented `/tools/invoke` message tool,
  pass the Django idempotency key, and count as sent only when a provider
  message ID is returned.
- CSV files can be imported from a campaign's Admin page. Importing remains
  separate from campaign activation and never sends synchronously in the web
  request.

## Deferred intentionally

Inbound reply ingestion and ActiveCampaign belong to later milestones. The
outbound WhatsApp adapter exists but is disabled by default and requires an
explicitly linked OpenClaw account before activation.
