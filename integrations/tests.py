from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase

from audit.models import AuditEvent
from campaigns.models import Campaign, CampaignMember
from candidates.models import Candidate
from messaging.models import Message
from .csv_import import CSVImportError, import_candidates_csv


HEADER = "first_name,last_name,phone,email,country,course_interest\n"


class CSVImportTests(TestCase):
    def setUp(self):
        self.campaign = Campaign.objects.create(name="September Admissions")

    def import_text(self, text: str):
        return import_candidates_csv(StringIO(text), campaign=self.campaign, default_phone_region="US")

    def test_imports_valid_candidates_and_memberships(self):
        report = self.import_text(
            HEADER
            + "Ana,Thomas,+14155552671,ANA@example.com,Saint Vincent,Python\n"
            + "Carlos,James,+442079460018,carlos@example.com,United Kingdom,Web Development\n"
        )
        self.assertEqual(report.imported, 2)
        self.assertEqual(report.processed, 2)
        self.assertEqual(Candidate.objects.get(first_name="Ana").email, "ana@example.com")
        self.assertEqual(CampaignMember.objects.filter(campaign=self.campaign).count(), 2)
        self.assertFalse(Message.objects.exists())
        self.assertTrue(AuditEvent.objects.filter(event_type=AuditEvent.EventType.CSV_IMPORTED).exists())

    def test_duplicate_rows_are_reported(self):
        report = self.import_text(
            HEADER
            + "Ana,Thomas,+14155552671,ana@example.com,US,Python\n"
            + "Ana,Thomas,+1 (415) 555-2671,other@example.com,US,Python\n"
        )
        self.assertEqual(report.imported, 1)
        self.assertEqual(report.duplicates, 1)
        self.assertEqual(Candidate.objects.count(), 1)

    def test_existing_candidate_is_updated_and_joined(self):
        candidate = Candidate.objects.create(
            first_name="Ana",
            phone="+14155552671",
            email="ana@example.com",
        )
        report = self.import_text(
            HEADER + "Ann,Thomas,+14155552671,ana@example.com,US,Data Science\n"
        )
        candidate.refresh_from_db()
        self.assertEqual(report.updated, 1)
        self.assertEqual(candidate.first_name, "Ann")
        self.assertEqual(candidate.status, Candidate.Status.READY)
        self.assertTrue(CampaignMember.objects.filter(campaign=self.campaign, candidate=candidate).exists())

    def test_import_preserves_meaningful_existing_candidate_status(self):
        candidate = Candidate.objects.create(
            first_name="Ana",
            phone="+14155552671",
            status=Candidate.Status.INTERESTED,
        )
        report = self.import_text(HEADER + "Ana,Thomas,+14155552671,,US,Python\n")
        candidate.refresh_from_db()
        self.assertEqual(report.updated, 1)
        self.assertEqual(candidate.status, Candidate.Status.INTERESTED)

    def test_existing_campaign_member_is_skipped(self):
        candidate = Candidate.objects.create(first_name="Ana", phone="+14155552671")
        CampaignMember.objects.create(campaign=self.campaign, candidate=candidate)
        report = self.import_text(HEADER + "Ana,Thomas,+14155552671,,US,Python\n")
        self.assertEqual(report.skipped, 1)
        self.assertEqual(CampaignMember.objects.count(), 1)

    def test_do_not_contact_candidate_is_not_added(self):
        Candidate.objects.create(first_name="Ana", phone="+14155552671", do_not_contact=True)
        report = self.import_text(HEADER + "Ana,Thomas,+14155552671,,US,Python\n")
        self.assertEqual(report.do_not_contact, 1)
        self.assertFalse(CampaignMember.objects.exists())

    def test_invalid_rows_are_reported_without_stopping_import(self):
        report = self.import_text(
            HEADER
            + "Missing Phone,User,not-a-number,user@example.com,US,Python\n"
            + "Valid,User,+14155552671,valid@example.com,US,Python\n"
        )
        self.assertEqual(report.invalid, 1)
        self.assertEqual(report.imported, 1)

    def test_missing_headers_rejects_entire_file(self):
        with self.assertRaises(CSVImportError):
            self.import_text("first_name,phone\nAna,+14155552671\n")

    def test_headers_are_trimmed(self):
        report = self.import_text(
            " first_name , last_name , phone , email , country , course_interest \n"
            "Ana,Thomas,+14155552671,ana@example.com,US,Python\n"
        )
        self.assertEqual(report.imported, 1)

    def test_command_imports_file_and_prints_report(self):
        output = StringIO()
        with TemporaryDirectory() as directory:
            path = Path(directory) / "candidates.csv"
            path.write_text(
                HEADER + "Ana,Thomas,+14155552671,ana@example.com,US,Python\n",
                encoding="utf-8",
            )
            call_command(
                "import_candidates",
                str(path),
                campaign_id=self.campaign.pk,
                default_region="US",
                stdout=output,
            )

        self.assertIn("Processed 1 candidate row(s).", output.getvalue())
        self.assertEqual(Candidate.objects.count(), 1)

    def test_conflicting_existing_phone_and_email_is_invalid(self):
        Candidate.objects.create(first_name="Phone", phone="+14155552671")
        Candidate.objects.create(first_name="Email", phone="+442079460018", email="same@example.com")
        report = self.import_text(
            HEADER + "Conflict,User,+14155552671,same@example.com,US,Python\n"
        )
        self.assertEqual(report.invalid, 1)
        self.assertFalse(CampaignMember.objects.exists())

    def test_database_rejects_duplicate_normalized_phone(self):
        Candidate.objects.create(first_name="First", phone="+14155552671")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Candidate.objects.create(first_name="Second", phone="(415) 555-2671")
