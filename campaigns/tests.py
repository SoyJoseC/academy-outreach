from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from candidates.models import Candidate
from .models import Campaign, CampaignMember


class CampaignTests(TestCase):
    def test_campaign_rejects_reversed_dates(self):
        campaign = Campaign(name="Admissions", start_at=timezone.now(), end_at=timezone.now() - timezone.timedelta(days=1))
        with self.assertRaises(ValidationError):
            campaign.full_clean()

    def test_candidate_can_only_join_campaign_once(self):
        campaign = Campaign.objects.create(name="Admissions")
        candidate = Candidate.objects.create(first_name="Carlos")
        CampaignMember.objects.create(campaign=campaign, candidate=candidate)
        with self.assertRaises(IntegrityError), transaction.atomic():
            CampaignMember.objects.create(campaign=campaign, candidate=candidate)

