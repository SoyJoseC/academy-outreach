from django.test import TestCase

from .models import Candidate


class CandidateTests(TestCase):
    def test_do_not_contact_forces_matching_status(self):
        candidate = Candidate.objects.create(first_name="Ana", do_not_contact=True)
        self.assertEqual(candidate.status, Candidate.Status.DO_NOT_CONTACT)

    def test_string_uses_full_name(self):
        candidate = Candidate(first_name="Ana", last_name="Thomas")
        self.assertEqual(str(candidate), "Ana Thomas")

