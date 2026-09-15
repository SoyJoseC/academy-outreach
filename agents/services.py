import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.module_loading import import_string

from audit.models import AuditEvent
from campaigns.models import CampaignMember
from messaging.models import Message

from .openclaw import OpenClawClient
from .schemas import (
    AdmissionsRequest,
    AgentAction,
    AgentDecision,
    CampaignContext,
    CandidateContext,
)

logger = logging.getLogger(__name__)


class GenerationOutcome(StrEnum):
    READY = "ready"
    HUMAN_REVIEW = "human_review"
    SKIPPED = "skipped"
    FAILED = "failed"
    CONTENDED = "contended"


@dataclass(frozen=True)
class GenerationResult:
    outcome: GenerationOutcome
    reason: str | None = None


class BaseAdmissionsAgent(ABC):
    @abstractmethod
    def recommend(self, request: AdmissionsRequest) -> AgentDecision:
        raise NotImplementedError


class TemplateAdmissionsAgent(BaseAdmissionsAgent):
    """Local safe default used until an OpenClaw Gateway is configured."""

    def recommend(self, request: AdmissionsRequest) -> AgentDecision:
        candidate = request.candidate
        greeting = f"Hi {candidate.first_name}" if candidate.first_name else "Hello"
        if candidate.course_interest:
            message = f"{greeting}, are you still interested in {candidate.course_interest}?"
        else:
            message = f"{greeting}, are you still interested in learning more about the academy?"
        return AgentDecision(AgentAction.SEND, message, False, None)


class OpenClawAdmissionsAgent(BaseAdmissionsAgent):
    def __init__(self, client: OpenClawClient | None = None):
        self.client = client or OpenClawClient()

    def recommend(self, request: AdmissionsRequest) -> AgentDecision:
        return self.client.recommend(request)


def get_admissions_agent() -> BaseAdmissionsAgent:
    agent_class = import_string(settings.ADMISSIONS_AGENT_BACKEND)
    agent = agent_class()
    if not isinstance(agent, BaseAdmissionsAgent):
        raise TypeError("ADMISSIONS_AGENT_BACKEND must implement BaseAdmissionsAgent.")
    return agent


def build_admissions_request(message: Message) -> AdmissionsRequest:
    return AdmissionsRequest(
        task="initial_outreach",
        candidate=CandidateContext(
            first_name=message.candidate.first_name,
            country=message.candidate.country,
            course_interest=message.candidate.course_interest,
        ),
        campaign=CampaignContext(
            name=message.campaign.name,
            objective=message.campaign.description,
        ),
    )


def _fail_generation(message: Message, reason: str) -> GenerationResult:
    message.status = Message.Status.FAILED
    message.failed_at = timezone.now()
    message.failure_reason = reason
    message.save(update_fields={"status", "failed_at", "failure_reason", "updated_at"})
    AuditEvent.objects.create(
        event_type=AuditEvent.EventType.AGENT_ERROR,
        description=reason,
        entity_type="Message",
        entity_id=str(message.pk),
    )
    logger.warning("agent error message_id=%s reason=%s", message.pk, reason)
    return GenerationResult(GenerationOutcome.FAILED, reason)


def generate_pending_message(
    message: Message,
    *,
    agent: BaseAdmissionsAgent | None = None,
) -> GenerationResult:
    claimed = Message.objects.filter(pk=message.pk, status=Message.Status.PENDING).update(
        status=Message.Status.GENERATING,
        updated_at=timezone.now(),
    )
    if not claimed:
        return GenerationResult(GenerationOutcome.CONTENDED, "Message was already claimed.")
    message = Message.objects.select_related("candidate", "campaign", "campaign_member").get(pk=message.pk)
    logger.info("message generation requested message_id=%s", message.pk)
    try:
        proposed = (agent or get_admissions_agent()).recommend(build_admissions_request(message))
        if not isinstance(proposed, AgentDecision):
            raise TypeError("Admissions agent returned an unvalidated response.")
        # Revalidate even typed custom backends so only the strict shared
        # contract can affect message state.
        decision = AgentDecision.from_mapping(proposed.to_dict())
    except Exception as exc:
        return _fail_generation(message, str(exc) or exc.__class__.__name__)

    now = timezone.now()
    with transaction.atomic():
        message = Message.objects.select_for_update().get(pk=message.pk)
        if message.status != Message.Status.GENERATING:
            return GenerationResult(GenerationOutcome.CONTENDED, "Message state changed during generation.")
        if decision.action == AgentAction.SEND:
            message.content = decision.message
            message.status = Message.Status.READY
            message.generated_at = now
            message.failure_reason = ""
            message.save(
                update_fields={"content", "status", "generated_at", "failure_reason", "updated_at"}
            )
            AuditEvent.objects.create(
                event_type=AuditEvent.EventType.MESSAGE_GENERATED,
                description="Validated admissions message generated.",
                entity_type="Message",
                entity_id=str(message.pk),
                metadata={"agent_action": decision.action.value},
            )
            logger.info("message generated message_id=%s", message.pk)
            return GenerationResult(GenerationOutcome.READY)

        reason = decision.reason or "Agent chose not to send."
        message.content = decision.message
        message.failure_reason = reason
        if decision.action == AgentAction.HUMAN_REVIEW:
            message.status = Message.Status.REQUIRES_HUMAN
            message.save(update_fields={"content", "status", "failure_reason", "updated_at"})
            CampaignMember.objects.filter(pk=message.campaign_member_id).update(
                human_required=True,
                updated_at=now,
            )
            AuditEvent.objects.create(
                event_type=AuditEvent.EventType.HUMAN_ESCALATION,
                description=reason,
                entity_type="Message",
                entity_id=str(message.pk),
                metadata={"campaign_member_id": message.campaign_member_id},
            )
            logger.info("human escalation message_id=%s reason=%s", message.pk, reason)
            return GenerationResult(GenerationOutcome.HUMAN_REVIEW, reason)

        message.status = Message.Status.CANCELLED
        message.save(update_fields={"content", "status", "failure_reason", "updated_at"})
        CampaignMember.objects.filter(pk=message.campaign_member_id).update(
            status=CampaignMember.Status.SKIPPED,
            updated_at=now,
        )
        AuditEvent.objects.create(
            event_type=AuditEvent.EventType.MESSAGE_BLOCKED,
            description=reason,
            entity_type="Message",
            entity_id=str(message.pk),
            metadata={"agent_action": decision.action.value},
        )
        return GenerationResult(GenerationOutcome.SKIPPED, reason)
