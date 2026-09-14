from django.core.exceptions import ValidationError
from django.test import TestCase

from campaigns.models import Campaign, CampaignMember
from candidates.models import Candidate
from .models import Message, SystemState


class MessageTests(TestCase):
    def setUp(self):
        self.candidate = Candidate.objects.create(first_name="Carlos")
        self.campaign = Campaign.objects.create(name="September Admissions")
        self.member = CampaignMember.objects.create(campaign=self.campaign, candidate=self.candidate)

    def make_message(self, **overrides):
        values = {
            "candidate": self.candidate,
            "campaign": self.campaign,
            "campaign_member": self.member,
            "direction": Message.Direction.OUTBOUND,
        }
        values.update(overrides)
        return Message.objects.create(**values)

    def test_valid_status_transition_sets_timestamp(self):
        message = self.make_message()
        message.transition_to(Message.Status.READY)
        self.assertEqual(message.status, Message.Status.READY)
        self.assertIsNotNone(message.generated_at)

    def test_invalid_status_transition_is_rejected(self):
        message = self.make_message()
        with self.assertRaises(ValidationError):
            message.transition_to(Message.Status.SENT)

    def test_message_membership_must_match_candidate(self):
        other = Candidate.objects.create(first_name="Other")
        message = Message(
            candidate=other,
            campaign=self.campaign,
            campaign_member=self.member,
            direction=Message.Direction.OUTBOUND,
        )
        with self.assertRaises(ValidationError):
            message.full_clean()


class SystemStateTests(TestCase):
    def test_load_creates_singleton(self):
        first = SystemState.load()
        second = SystemState.load()
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(SystemState.objects.count(), 1)

    def test_second_save_updates_singleton(self):
        self.assertTrue(SystemState.load().outbound_enabled)
        SystemState(outbound_enabled=False, paused_reason="Maintenance").save()
        self.assertEqual(SystemState.objects.count(), 1)
        self.assertFalse(SystemState.load().outbound_enabled)
