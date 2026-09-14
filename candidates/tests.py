from django.test import TestCase

from .models import Candidate
from .normalization import PhoneNormalizationError, normalize_email, normalize_phone


class CandidateTests(TestCase):
    def test_do_not_contact_forces_matching_status(self):
        candidate = Candidate.objects.create(first_name="Ana", do_not_contact=True)
        self.assertEqual(candidate.status, Candidate.Status.DO_NOT_CONTACT)

    def test_string_uses_full_name(self):
        candidate = Candidate(first_name="Ana", last_name="Thomas")
        self.assertEqual(str(candidate), "Ana Thomas")


class NormalizationTests(TestCase):
    def test_phone_is_normalized_to_e164(self):
        self.assertEqual(normalize_phone("(415) 555-2671", default_region="US"), "+14155552671")

    def test_invalid_phone_is_rejected(self):
        with self.assertRaises(PhoneNormalizationError):
            normalize_phone("123", default_region="US")

    def test_email_is_trimmed_and_lowercased(self):
        self.assertEqual(normalize_email("  Ana@Example.COM "), "ana@example.com")

    def test_model_normalizes_contact_fields_on_save(self):
        candidate = Candidate.objects.create(
            first_name="Ana",
            phone="(415) 555-2671",
            email="Ana@Example.COM",
        )
        self.assertEqual(candidate.phone, "+14155552671")
        self.assertEqual(candidate.email, "ana@example.com")

