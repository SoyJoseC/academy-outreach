from django.contrib.auth import get_user_model
from django.db import transaction

from audit.models import AuditEvent

from .models import SystemState


@transaction.atomic
def set_outbound_enabled(
    enabled: bool,
    *,
    reason: str = "",
    actor: get_user_model() | None = None,
) -> SystemState:
    state = SystemState.load()
    state = SystemState.objects.select_for_update().get(pk=state.pk)
    changed = state.outbound_enabled != enabled
    state.outbound_enabled = enabled
    state.paused_reason = "" if enabled else reason
    state.updated_by = actor
    state.save()
    if changed:
        AuditEvent.objects.create(
            event_type=(AuditEvent.EventType.SYSTEM_RESUMED if enabled else AuditEvent.EventType.SYSTEM_PAUSED),
            description=state.paused_reason,
            entity_type="SystemState",
            entity_id=str(state.pk),
            actor=actor,
        )
    return state
