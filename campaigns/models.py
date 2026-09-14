from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q

from candidates.models import Candidate


class Campaign(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        ACTIVE = "ACTIVE", "Active"
        PAUSED = "PAUSED", "Paused"
        COMPLETED = "COMPLETED", "Completed"
        CANCELLED = "CANCELLED", "Cancelled"

    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT, db_index=True)
    start_at = models.DateTimeField(null=True, blank=True)
    end_at = models.DateTimeField(null=True, blank=True)
    min_message_interval_seconds = models.PositiveIntegerField(default=120)
    hourly_limit = models.PositiveIntegerField(default=20)
    daily_limit = models.PositiveIntegerField(default=100)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.CheckConstraint(condition=Q(hourly_limit__gt=0), name="campaign_hourly_limit_gt_zero"),
            models.CheckConstraint(condition=Q(daily_limit__gt=0), name="campaign_daily_limit_gt_zero"),
            models.CheckConstraint(
                condition=Q(start_at__isnull=True) | Q(end_at__isnull=True) | Q(start_at__lte=F("end_at")),
                name="campaign_dates_in_order",
            ),
        ]

    def clean(self):
        if self.start_at and self.end_at and self.start_at > self.end_at:
            raise ValidationError({"end_at": "End date must not be earlier than start date."})

    def __str__(self) -> str:
        return self.name


class CampaignMember(models.Model):
    class Status(models.TextChoices):
        READY = "READY", "Ready"
        CONTACTED = "CONTACTED", "Contacted"
        REPLIED = "REPLIED", "Replied"
        INTERESTED = "INTERESTED", "Interested"
        NOT_INTERESTED = "NOT_INTERESTED", "Not interested"
        COMPLETED = "COMPLETED", "Completed"
        SKIPPED = "SKIPPED", "Skipped"

    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name="members")
    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE, related_name="campaign_memberships")
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.READY, db_index=True)
    first_contact_at = models.DateTimeField(null=True, blank=True)
    last_contact_at = models.DateTimeField(null=True, blank=True)
    messages_sent = models.PositiveIntegerField(default=0)
    replies_received = models.PositiveIntegerField(default=0)
    human_required = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("campaign", "candidate")
        constraints = [
            models.UniqueConstraint(fields=("campaign", "candidate"), name="unique_candidate_per_campaign"),
            models.CheckConstraint(
                condition=Q(first_contact_at__isnull=True)
                | Q(last_contact_at__isnull=True)
                | Q(first_contact_at__lte=F("last_contact_at")),
                name="campaign_member_contact_dates_in_order",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.campaign}: {self.candidate}"

