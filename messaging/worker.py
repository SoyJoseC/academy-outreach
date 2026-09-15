import logging
from dataclasses import dataclass
from datetime import timedelta

from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from agents.services import BaseAdmissionsAgent, GenerationOutcome, generate_pending_message
from audit.models import AuditEvent
from campaigns.models import CampaignMember
from candidates.models import Candidate

from .models import Message, SystemState
from .policies import PolicyDecision, PolicyReason, evaluate_outbound
from .queue import enqueue_next_eligible
from .sender import BaseSender, get_sender

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WorkerResult:
    outcome: str
    message_id: int | None = None
    reason: str | None = None


PERMANENT_BLOCKS = {
    PolicyReason.DO_NOT_CONTACT,
    PolicyReason.DUPLICATE,
    PolicyReason.INVALID_CANDIDATE,
}
DEFERRED_BLOCKS = {
    PolicyReason.CAMPAIGN_INACTIVE,
    PolicyReason.MESSAGE_INTERVAL,
    PolicyReason.RATE_LIMIT_HOURLY,
    PolicyReason.RATE_LIMIT_DAILY,
}


def _record_block(message: Message, decision: PolicyDecision) -> WorkerResult:
    reason = str(decision.reason)
    if decision.reason in PERMANENT_BLOCKS:
        message.status = Message.Status.CANCELLED
        message.failure_reason = reason
        message.save(update_fields={"status", "failure_reason", "updated_at"})
    elif decision.reason == PolicyReason.REQUIRES_HUMAN:
        message.status = Message.Status.REQUIRES_HUMAN
        message.failure_reason = reason
        message.save(update_fields={"status", "failure_reason", "updated_at"})
    elif decision.reason in DEFERRED_BLOCKS:
        message.scheduled_at = timezone.now() + timedelta(seconds=60)
        message.failure_reason = reason
        message.save(update_fields={"scheduled_at", "failure_reason", "updated_at"})
    AuditEvent.objects.create(
        event_type=AuditEvent.EventType.MESSAGE_BLOCKED,
        description=reason,
        entity_type="Message",
        entity_id=str(message.pk),
        metadata={"reason": reason},
    )
    logger.info("message blocked message_id=%s reason=%s", message.pk, reason)
    return WorkerResult("blocked", message.pk, reason)


def _next_due_message() -> Message | None:
    now = timezone.now()
    return (
        Message.objects.select_related("candidate", "campaign", "campaign_member")
        .filter(
            direction=Message.Direction.OUTBOUND,
            status__in=(Message.Status.PENDING, Message.Status.READY),
        )
        .filter(Q(scheduled_at__isnull=True) | Q(scheduled_at__lte=now))
        .order_by("scheduled_at", "created_at", "pk")
        .first()
    )


def process_next(
    sender: BaseSender | None = None,
    agent: BaseAdmissionsAgent | None = None,
) -> WorkerResult:
    if not SystemState.load().outbound_enabled:
        return WorkerResult("blocked", reason=str(PolicyReason.SYSTEM_PAUSED))

    message = _next_due_message()
    if message is None:
        message = enqueue_next_eligible()
    if message is None:
        return WorkerResult("idle")

    if message.status == Message.Status.PENDING:
        pre_generation_decision = evaluate_outbound(message, require_content=False)
        logger.info(
            "pre-generation policy check message_id=%s allowed=%s reason=%s",
            message.pk,
            pre_generation_decision.allowed,
            pre_generation_decision.reason or "PASS",
        )
        if not pre_generation_decision.allowed:
            return _record_block(message, pre_generation_decision)
        generation = generate_pending_message(message, agent=agent)
        if generation.outcome != GenerationOutcome.READY:
            return WorkerResult(generation.outcome, message.pk, generation.reason)
        message = Message.objects.select_related("candidate", "campaign", "campaign_member").get(
            pk=message.pk
        )

    decision = evaluate_outbound(message)
    logger.info(
        "policy check message_id=%s allowed=%s reason=%s",
        message.pk,
        decision.allowed,
        decision.reason or "PASS",
    )
    if not decision.allowed:
        return _record_block(message, decision)

    claimed = Message.objects.filter(pk=message.pk, status=Message.Status.READY).update(
        status=Message.Status.SENDING,
        updated_at=timezone.now(),
    )
    if not claimed:
        return WorkerResult("contended", message.pk)
    message.refresh_from_db()

    final_decision = evaluate_outbound(message)
    logger.info(
        "final policy check message_id=%s allowed=%s reason=%s",
        message.pk,
        final_decision.allowed,
        final_decision.reason or "PASS",
    )
    if not final_decision.allowed:
        message.status = Message.Status.READY
        message.save(update_fields={"status", "updated_at"})
        return _record_block(message, final_decision)

    sender = sender or get_sender()
    AuditEvent.objects.create(
        event_type=AuditEvent.EventType.MESSAGE_APPROVED,
        description="Final deterministic policy check passed.",
        entity_type="Message",
        entity_id=str(message.pk),
    )
    try:
        result = sender.send(message)
        failure_reason = result.failure_reason
    except Exception as exc:  # Sender boundaries must not crash the worker.
        logger.exception("worker sender error message_id=%s", message.pk)
        result = None
        failure_reason = str(exc)

    if result is None or not result.success:
        message.status = Message.Status.FAILED
        message.failed_at = timezone.now()
        message.retry_count = F("retry_count") + 1
        message.failure_reason = failure_reason or "Sender failed without a reason."
        message.save(update_fields={"status", "failed_at", "retry_count", "failure_reason", "updated_at"})
        message.refresh_from_db(fields=("retry_count",))
        AuditEvent.objects.create(
            event_type=AuditEvent.EventType.MESSAGE_FAILED,
            description=message.failure_reason,
            entity_type="Message",
            entity_id=str(message.pk),
        )
        logger.info("message failed message_id=%s reason=%s", message.pk, message.failure_reason)
        return WorkerResult("failed", message.pk, message.failure_reason)

    sent_at = timezone.now()
    with transaction.atomic():
        message.status = Message.Status.SENT
        message.sent_at = sent_at
        message.provider_message_id = result.provider_message_id
        message.failure_reason = ""
        message.save(
            update_fields={"status", "sent_at", "provider_message_id", "failure_reason", "updated_at"}
        )
        member = CampaignMember.objects.select_for_update().get(pk=message.campaign_member_id)
        member.messages_sent = F("messages_sent") + 1
        member.first_contact_at = member.first_contact_at or sent_at
        member.last_contact_at = sent_at
        member.status = CampaignMember.Status.CONTACTED
        member.save(
            update_fields={"messages_sent", "first_contact_at", "last_contact_at", "status", "updated_at"}
        )
        if message.candidate.status == Candidate.Status.READY:
            Candidate.objects.filter(pk=message.candidate_id, status=Candidate.Status.READY).update(
                status=Candidate.Status.CONTACTED,
                updated_at=sent_at,
            )
        AuditEvent.objects.create(
            event_type=AuditEvent.EventType.MESSAGE_SENT,
            description="Message confirmed by configured sender.",
            entity_type="Message",
            entity_id=str(message.pk),
            metadata={"provider_message_id": result.provider_message_id},
        )
    logger.info("message sent message_id=%s provider_id=%s", message.pk, result.provider_message_id)
    return WorkerResult("sent", message.pk)
