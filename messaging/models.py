from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from campaigns.models import Campaign, CampaignMember
from candidates.models import Candidate


class Message(models.Model):
    class Direction(models.TextChoices):
        INBOUND = "INBOUND", "Inbound"
        OUTBOUND = "OUTBOUND", "Outbound"

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        GENERATING = "GENERATING", "Generating"
        READY = "READY", "Ready"
        SENDING = "SENDING", "Sending"
        SENT = "SENT", "Sent"
        DELIVERED = "DELIVERED", "Delivered"
        FAILED = "FAILED", "Failed"
        CANCELLED = "CANCELLED", "Cancelled"
        REQUIRES_HUMAN = "REQUIRES_HUMAN", "Requires human"

    ALLOWED_TRANSITIONS = {
        Status.PENDING: {Status.GENERATING, Status.READY, Status.CANCELLED, Status.REQUIRES_HUMAN},
        Status.GENERATING: {Status.READY, Status.FAILED, Status.CANCELLED, Status.REQUIRES_HUMAN},
        Status.READY: {Status.SENDING, Status.CANCELLED, Status.REQUIRES_HUMAN},
        Status.SENDING: {Status.SENT, Status.FAILED},
        Status.SENT: {Status.DELIVERED},
        Status.DELIVERED: set(),
        Status.FAILED: {Status.PENDING, Status.CANCELLED, Status.REQUIRES_HUMAN},
        Status.CANCELLED: set(),
        Status.REQUIRES_HUMAN: {Status.READY, Status.CANCELLED},
    }

    candidate = models.ForeignKey(Candidate, on_delete=models.PROTECT, related_name="messages")
    campaign = models.ForeignKey(Campaign, on_delete=models.PROTECT, related_name="messages")
    campaign_member = models.ForeignKey(CampaignMember, on_delete=models.PROTECT, related_name="messages")
    direction = models.CharField(max_length=8, choices=Direction.choices)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.PENDING, db_index=True)
    content = models.TextField(blank=True)
    scheduled_at = models.DateTimeField(null=True, blank=True, db_index=True)
    generated_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True, db_index=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)
    provider_message_id = models.CharField(max_length=255, blank=True, db_index=True)
    retry_count = models.PositiveIntegerField(default=0)
    failure_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [models.Index(fields=("direction", "status", "scheduled_at"), name="message_queue_lookup")]

    def clean(self):
        errors = {}
        if self.campaign_member_id:
            if self.candidate_id and self.campaign_member.candidate_id != self.candidate_id:
                errors["candidate"] = "Candidate must match the campaign member."
            if self.campaign_id and self.campaign_member.campaign_id != self.campaign_id:
                errors["campaign"] = "Campaign must match the campaign member."
        if errors:
            raise ValidationError(errors)

    def transition_to(self, new_status: str, *, save: bool = True) -> None:
        if new_status not in self.ALLOWED_TRANSITIONS.get(self.status, set()):
            raise ValidationError(f"Invalid message transition: {self.status} -> {new_status}")

        now = timezone.now()
        self.status = new_status
        timestamp_fields = {
            self.Status.READY: "generated_at",
            self.Status.SENT: "sent_at",
            self.Status.DELIVERED: "delivered_at",
            self.Status.FAILED: "failed_at",
        }
        if field := timestamp_fields.get(new_status):
            setattr(self, field, now)
        if save:
            self.save()

    def __str__(self) -> str:
        return f"{self.direction} message #{self.pk or 'new'} for {self.candidate}"


class SystemState(models.Model):
    outbound_enabled = models.BooleanField(default=True)
    inbound_auto_reply_enabled = models.BooleanField(default=False)
    paused_reason = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="system_state_updates",
    )

    class Meta:
        verbose_name = "system state"
        verbose_name_plural = "system state"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        state, _ = cls.objects.get_or_create(pk=1)
        return state

    def __str__(self) -> str:
        return "Outbound enabled" if self.outbound_enabled else "Outbound paused"

