from django.db import models
from django.db.models import Q

from .normalization import normalize_email, normalize_phone


class Candidate(models.Model):
    class Status(models.TextChoices):
        NEW = "NEW", "New"
        READY = "READY", "Ready"
        CONTACTED = "CONTACTED", "Contacted"
        REPLIED = "REPLIED", "Replied"
        INTERESTED = "INTERESTED", "Interested"
        NOT_INTERESTED = "NOT_INTERESTED", "Not interested"
        REQUIRES_HUMAN = "REQUIRES_HUMAN", "Requires human"
        DO_NOT_CONTACT = "DO_NOT_CONTACT", "Do not contact"
        INVALID = "INVALID", "Invalid"

    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100, blank=True)
    phone = models.CharField(max_length=32, blank=True, db_index=True)
    email = models.EmailField(blank=True, db_index=True)
    country = models.CharField(max_length=100, blank=True)
    course_interest = models.CharField(max_length=255, blank=True)
    source = models.CharField(max_length=100, blank=True)
    activecampaign_id = models.CharField(max_length=100, blank=True, db_index=True)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.NEW, db_index=True)
    do_not_contact = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("last_name", "first_name", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("phone",),
                condition=~Q(phone=""),
                name="unique_nonblank_candidate_phone",
            ),
            models.UniqueConstraint(
                fields=("email",),
                condition=~Q(email=""),
                name="unique_nonblank_candidate_email",
            ),
        ]

    def save(self, *args, **kwargs):
        self.phone = normalize_phone(self.phone)
        self.email = normalize_email(self.email)
        if self.do_not_contact:
            self.status = self.Status.DO_NOT_CONTACT
            if update_fields := kwargs.get("update_fields"):
                kwargs["update_fields"] = set(update_fields) | {"status"}
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()
