from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
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


class CampaignAdminImportTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="test-password",
        )
        self.client.force_login(self.user)
        self.campaign = Campaign.objects.create(name="September Admissions")
        self.url = reverse(
            "admin:campaigns_campaign_import_candidates",
            args=(self.campaign.pk,),
        )

    def test_admin_can_import_candidates_into_campaign(self):
        csv_content = (
            "first_name,last_name,phone,email,country,course_interest\n"
            "Ana,Thomas,+17845551234,ana@example.com,SVG,Python\n"
        )
        upload = SimpleUploadedFile("candidates.csv", csv_content.encode(), "text/csv")

        response = self.client.post(self.url, {"csv_file": upload})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Processed 1 rows")
        candidate = Candidate.objects.get(phone="+17845551234")
        self.assertTrue(
            CampaignMember.objects.filter(campaign=self.campaign, candidate=candidate).exists()
        )

    def test_admin_import_reports_invalid_rows(self):
        csv_content = (
            "first_name,last_name,phone,email,country,course_interest\n"
            "Ana,Thomas,invalid,ana@example.com,SVG,Python\n"
        )
        upload = SimpleUploadedFile("candidates.csv", csv_content.encode(), "text/csv")

        response = self.client.post(self.url, {"csv_file": upload})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Rows needing attention")
        self.assertContains(response, "Phone number could not be parsed")
        self.assertFalse(Candidate.objects.exists())
