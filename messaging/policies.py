from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from django.db.models import Q
from django.utils import timezone

from candidates.models import Candidate

from .models import Message, SystemState


class PolicyReason(StrEnum):
    SYSTEM_PAUSED = "SYSTEM_PAUSED"
    CAMPAIGN_INACTIVE = "CAMPAIGN_INACTIVE"
    DO_NOT_CONTACT = "DO_NOT_CONTACT"
    DUPLICATE = "DUPLICATE"
    MESSAGE_INTERVAL = "MESSAGE_INTERVAL"
    RATE_LIMIT_HOURLY = "RATE_LIMIT_HOURLY"
    RATE_LIMIT_DAILY = "RATE_LIMIT_DAILY"
    REQUIRES_HUMAN = "REQUIRES_HUMAN"
    INVALID_CANDIDATE = "INVALID_CANDIDATE"


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: PolicyReason | None = None


SENT_STATUSES = (Message.Status.SENT, Message.Status.DELIVERED)


def evaluate_outbound(message: Message, *, now: datetime | None = None) -> PolicyDecision:
    """Apply deterministic rules. AI output is never consulted here."""
    now = now or timezone.now()
    state = SystemState.load()
    campaign = message.campaign
    candidate = message.candidate
    member = message.campaign_member

    if not state.outbound_enabled:
        return PolicyDecision(False, PolicyReason.SYSTEM_PAUSED)
    if campaign.status != campaign.Status.ACTIVE:
        return PolicyDecision(False, PolicyReason.CAMPAIGN_INACTIVE)
    if (campaign.start_at and campaign.start_at > now) or (campaign.end_at and campaign.end_at < now):
        return PolicyDecision(False, PolicyReason.CAMPAIGN_INACTIVE)
    if candidate.do_not_contact or candidate.status == Candidate.Status.DO_NOT_CONTACT:
        return PolicyDecision(False, PolicyReason.DO_NOT_CONTACT)
    if member.human_required or candidate.status == Candidate.Status.REQUIRES_HUMAN:
        return PolicyDecision(False, PolicyReason.REQUIRES_HUMAN)
    if (
        message.direction != Message.Direction.OUTBOUND
        or not candidate.phone
        or candidate.status == Candidate.Status.INVALID
        or not message.content.strip()
    ):
        return PolicyDecision(False, PolicyReason.INVALID_CANDIDATE)

    if message.idempotency_key and Message.objects.filter(
        idempotency_key=message.idempotency_key,
        status__in=(*SENT_STATUSES, Message.Status.SENDING),
    ).exclude(pk=message.pk).exists():
        return PolicyDecision(False, PolicyReason.DUPLICATE)

    previous_sent = (
        Message.objects.filter(
            campaign_member=member,
            direction=Message.Direction.OUTBOUND,
            status__in=SENT_STATUSES,
            sent_at__isnull=False,
        )
        .exclude(pk=message.pk)
        .order_by("-sent_at")
        .first()
    )
    if previous_sent and previous_sent.sent_at + timedelta(seconds=campaign.min_message_interval_seconds) > now:
        return PolicyDecision(False, PolicyReason.MESSAGE_INTERVAL)

    sent = Message.objects.filter(
        campaign=campaign,
        direction=Message.Direction.OUTBOUND,
        status__in=SENT_STATUSES,
        sent_at__isnull=False,
    ).exclude(pk=message.pk)
    if sent.filter(sent_at__gte=now - timedelta(hours=1)).count() >= campaign.hourly_limit:
        return PolicyDecision(False, PolicyReason.RATE_LIMIT_HOURLY)
    day_start = now.astimezone(timezone.get_current_timezone()).replace(hour=0, minute=0, second=0, microsecond=0)
    if sent.filter(sent_at__gte=day_start).count() >= campaign.daily_limit:
        return PolicyDecision(False, PolicyReason.RATE_LIMIT_DAILY)

    return PolicyDecision(True)
