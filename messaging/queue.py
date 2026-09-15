import logging

from django.db import IntegrityError, transaction
from django.utils import timezone

from audit.models import AuditEvent
from campaigns.models import CampaignMember
from candidates.models import Candidate

from .models import Message

logger = logging.getLogger(__name__)


def build_test_message(member: CampaignMember) -> str:
    candidate = member.candidate
    greeting = f"Hi {candidate.first_name}" if candidate.first_name else "Hello"
    if candidate.course_interest:
        return f"{greeting}, are you still interested in {candidate.course_interest}?"
    return f"{greeting}, are you still interested in learning more about the academy?"


@transaction.atomic
def enqueue_initial_message(member: CampaignMember) -> tuple[Message, bool]:
    """Create exactly one initial message per campaign membership."""
    member = CampaignMember.objects.select_for_update().select_related("candidate", "campaign").get(pk=member.pk)
    key = f"initial-outreach:{member.pk}"
    try:
        # The savepoint keeps the outer transaction usable if another worker
        # wins the unique-key race between lookup and insert.
        with transaction.atomic():
            message, created = Message.objects.get_or_create(
                idempotency_key=key,
                defaults={
                    "candidate": member.candidate,
                    "campaign": member.campaign,
                    "campaign_member": member,
                    "direction": Message.Direction.OUTBOUND,
                    "status": Message.Status.READY,
                    "content": build_test_message(member),
                    "generated_at": timezone.now(),
                    "scheduled_at": timezone.now(),
                },
            )
    except IntegrityError:
        message = Message.objects.get(idempotency_key=key)
        created = False

    if created:
        AuditEvent.objects.create(
            event_type=AuditEvent.EventType.MESSAGE_GENERATED,
            description="Deterministic test message queued.",
            entity_type="Message",
            entity_id=str(message.pk),
            metadata={"campaign_member_id": member.pk},
        )
        logger.info(
            "message generated message_id=%s candidate_id=%s campaign_id=%s",
            message.pk,
            member.candidate_id,
            member.campaign_id,
        )
    return message, created


def enqueue_next_eligible() -> Message | None:
    member = (
        CampaignMember.objects.select_related("candidate", "campaign")
        .filter(
            status=CampaignMember.Status.READY,
            human_required=False,
            campaign__status="ACTIVE",
            candidate__status=Candidate.Status.READY,
            candidate__do_not_contact=False,
        )
        .exclude(messages__idempotency_key__startswith="initial-outreach:")
        .order_by("created_at", "pk")
        .first()
    )
    if not member:
        return None
    logger.info("candidate selected candidate_id=%s campaign_id=%s", member.candidate_id, member.campaign_id)
    return enqueue_initial_message(member)[0]
