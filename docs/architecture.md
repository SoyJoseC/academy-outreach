# Milestone 1 architecture

## Responsibility boundaries

- `candidates` owns person-level admissions and contact eligibility data.
- `campaigns` owns campaigns and candidate participation within each campaign.
- `messaging` owns auditable message state and the global automation switch.
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

## Deferred intentionally

CSV processing, phone normalization, queue locking, rate limiting, FakeSender,
OpenClaw, inbound webhooks, WhatsApp, and ActiveCampaign belong to later
milestones. No production messaging path exists in Milestone 1.

