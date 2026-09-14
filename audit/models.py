from django.conf import settings
from django.db import models


class AuditEvent(models.Model):
    class EventType(models.TextChoices):
        CSV_IMPORTED = "CSV_IMPORTED", "CSV imported"
        CANDIDATE_CREATED = "CANDIDATE_CREATED", "Candidate created"
        DUPLICATE_DETECTED = "DUPLICATE_DETECTED", "Duplicate detected"
        CAMPAIGN_MEMBER_CREATED = "CAMPAIGN_MEMBER_CREATED", "Campaign member created"
        MESSAGE_GENERATED = "MESSAGE_GENERATED", "Message generated"
        MESSAGE_APPROVED = "MESSAGE_APPROVED", "Message approved"
        MESSAGE_BLOCKED = "MESSAGE_BLOCKED", "Message blocked"
        MESSAGE_SENT = "MESSAGE_SENT", "Message sent"
        MESSAGE_FAILED = "MESSAGE_FAILED", "Message failed"
        OPT_OUT_DETECTED = "OPT_OUT_DETECTED", "Opt-out detected"
        SYSTEM_PAUSED = "SYSTEM_PAUSED", "System paused"
        SYSTEM_RESUMED = "SYSTEM_RESUMED", "System resumed"
        HUMAN_ESCALATION = "HUMAN_ESCALATION", "Human escalation"
        AGENT_ERROR = "AGENT_ERROR", "Agent error"

    event_type = models.CharField(max_length=40, choices=EventType.choices, db_index=True)
    description = models.TextField(blank=True)
    entity_type = models.CharField(max_length=100, blank=True, db_index=True)
    entity_id = models.CharField(max_length=100, blank=True, db_index=True)
    metadata = models.JSONField(default=dict, blank=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_events",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [models.Index(fields=("entity_type", "entity_id", "created_at"), name="audit_entity_history")]

    def __str__(self) -> str:
        return f"{self.event_type} at {self.created_at:%Y-%m-%d %H:%M:%S}"

