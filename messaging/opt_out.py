import logging
import re

from django.db import transaction

from audit.models import AuditEvent
from candidates.models import Candidate

logger = logging.getLogger(__name__)


OPT_OUT_PATTERNS = (
    re.compile(r"\bstop\b", re.IGNORECASE),
    re.compile(r"\bunsubscribe\b", re.IGNORECASE),
    re.compile(r"\bremove\s+me\b", re.IGNORECASE),
    re.compile(r"\bdo\s+not\s+contact\s+me\b", re.IGNORECASE),
    re.compile(r"\bdon'?t\s+message\s+me\b", re.IGNORECASE),
)


def detects_opt_out(content: str) -> bool:
    normalized = " ".join((content or "").split())
    return any(pattern.search(normalized) for pattern in OPT_OUT_PATTERNS)


@transaction.atomic
def apply_opt_out(candidate: Candidate, content: str) -> bool:
    if not detects_opt_out(content):
        return False

    locked = Candidate.objects.select_for_update().get(pk=candidate.pk)
    already_blocked = locked.do_not_contact
    locked.do_not_contact = True
    locked.status = Candidate.Status.DO_NOT_CONTACT
    locked.save(update_fields={"do_not_contact", "status", "updated_at"})
    if not already_blocked:
        AuditEvent.objects.create(
            event_type=AuditEvent.EventType.OPT_OUT_DETECTED,
            description="Candidate opt-out detected by deterministic matching.",
            entity_type="Candidate",
            entity_id=str(locked.pk),
            metadata={"matched": True},
        )
        logger.info("opt-out candidate_id=%s", locked.pk)
    return True
