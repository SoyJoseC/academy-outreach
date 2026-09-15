from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.utils import timezone

from audit.models import AuditEvent
from campaigns.models import Campaign, CampaignMember
from candidates.models import Candidate
from .models import Message, SystemState
from .opt_out import apply_opt_out, detects_opt_out
from .policies import PolicyReason, evaluate_outbound
from .queue import enqueue_initial_message
from .sender import BaseSender, FakeSender, OpenClawWhatsAppSender, SendResult
from .system_state import set_outbound_enabled
from .worker import process_next


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

    def test_pause_service_records_audit_event(self):
        set_outbound_enabled(False, reason="Maintenance")
        state = SystemState.load()
        self.assertFalse(state.outbound_enabled)
        self.assertEqual(state.paused_reason, "Maintenance")
        self.assertTrue(AuditEvent.objects.filter(event_type=AuditEvent.EventType.SYSTEM_PAUSED).exists())


class MessagingSafetyTestCase(TestCase):
    def setUp(self):
        self.now = timezone.now()
        self.candidate = Candidate.objects.create(
            first_name="Carlos",
            phone="+17845551234",
            status=Candidate.Status.READY,
            course_interest="Web Development",
        )
        self.campaign = Campaign.objects.create(
            name="September Admissions",
            status=Campaign.Status.ACTIVE,
            hourly_limit=20,
            daily_limit=100,
        )
        self.member = CampaignMember.objects.create(campaign=self.campaign, candidate=self.candidate)
        SystemState.load()

    def make_ready_message(self, **overrides):
        values = {
            "candidate": self.candidate,
            "campaign": self.campaign,
            "campaign_member": self.member,
            "direction": Message.Direction.OUTBOUND,
            "status": Message.Status.READY,
            "content": "Hi Carlos",
            "generated_at": self.now,
        }
        values.update(overrides)
        return Message.objects.create(**values)

    def add_sent_message(self, *, sent_at=None, key=""):
        candidate = Candidate.objects.create(
            first_name=f"Sent {Candidate.objects.count()}",
            phone=f"+1784555{Candidate.objects.count():04d}",
            status=Candidate.Status.CONTACTED,
        )
        member = CampaignMember.objects.create(
            campaign=self.campaign,
            candidate=candidate,
            status=CampaignMember.Status.CONTACTED,
        )
        return Message.objects.create(
            candidate=candidate,
            campaign=self.campaign,
            campaign_member=member,
            direction=Message.Direction.OUTBOUND,
            status=Message.Status.SENT,
            content="Previously sent",
            sent_at=sent_at or self.now,
            idempotency_key=key,
        )


class PolicyTests(MessagingSafetyTestCase):
    def test_system_pause_blocks_message(self):
        set_outbound_enabled(False, reason="Maintenance")
        decision = evaluate_outbound(self.make_ready_message(), now=self.now)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, PolicyReason.SYSTEM_PAUSED)

    def test_inactive_campaign_blocks_message(self):
        self.campaign.status = Campaign.Status.PAUSED
        self.campaign.save(update_fields={"status"})
        decision = evaluate_outbound(self.make_ready_message(), now=self.now)
        self.assertEqual(decision.reason, PolicyReason.CAMPAIGN_INACTIVE)

    def test_do_not_contact_blocks_message(self):
        self.candidate.do_not_contact = True
        self.candidate.save(update_fields={"do_not_contact"})
        decision = evaluate_outbound(self.make_ready_message(), now=self.now)
        self.assertEqual(decision.reason, PolicyReason.DO_NOT_CONTACT)

    def test_human_review_lock_blocks_message(self):
        self.member.human_required = True
        self.member.save(update_fields={"human_required"})
        decision = evaluate_outbound(self.make_ready_message(), now=self.now)
        self.assertEqual(decision.reason, PolicyReason.REQUIRES_HUMAN)

    def test_candidate_without_phone_is_invalid(self):
        self.candidate.phone = ""
        self.candidate.save(update_fields={"phone"})
        decision = evaluate_outbound(self.make_ready_message(), now=self.now)
        self.assertEqual(decision.reason, PolicyReason.INVALID_CANDIDATE)

    def test_minimum_message_interval_is_enforced(self):
        previous = self.make_ready_message(status=Message.Status.SENT, sent_at=self.now)
        current = self.make_ready_message()
        decision = evaluate_outbound(current, now=self.now)
        self.assertEqual(previous.status, Message.Status.SENT)
        self.assertEqual(decision.reason, PolicyReason.MESSAGE_INTERVAL)

    def test_hourly_limit_is_enforced(self):
        self.campaign.hourly_limit = 1
        self.campaign.min_message_interval_seconds = 0
        self.campaign.save(update_fields={"hourly_limit", "min_message_interval_seconds"})
        self.add_sent_message()
        decision = evaluate_outbound(self.make_ready_message(), now=self.now)
        self.assertEqual(decision.reason, PolicyReason.RATE_LIMIT_HOURLY)

    def test_daily_limit_is_enforced(self):
        self.campaign.hourly_limit = 100
        self.campaign.daily_limit = 1
        self.campaign.min_message_interval_seconds = 0
        self.campaign.save(update_fields={"hourly_limit", "daily_limit", "min_message_interval_seconds"})
        self.add_sent_message()
        decision = evaluate_outbound(self.make_ready_message(), now=self.now)
        self.assertEqual(decision.reason, PolicyReason.RATE_LIMIT_DAILY)

    def test_duplicate_idempotency_key_is_rejected_by_database(self):
        self.add_sent_message(key="shared-key")
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.make_ready_message(idempotency_key="shared-key")

    def test_valid_message_is_allowed(self):
        self.assertTrue(evaluate_outbound(self.make_ready_message(), now=self.now).allowed)


class OptOutTests(MessagingSafetyTestCase):
    def test_common_phrases_are_detected_case_insensitively(self):
        for phrase in ("STOP", "unsubscribe please", "Remove   me", "don't message me again"):
            with self.subTest(phrase=phrase):
                self.assertTrue(detects_opt_out(phrase))

    def test_unrelated_reply_is_not_an_opt_out(self):
        self.assertFalse(detects_opt_out("Please send the programme details"))

    def test_apply_opt_out_updates_candidate_and_audits(self):
        self.assertTrue(apply_opt_out(self.candidate, "Do not contact me"))
        self.candidate.refresh_from_db()
        self.assertTrue(self.candidate.do_not_contact)
        self.assertEqual(self.candidate.status, Candidate.Status.DO_NOT_CONTACT)
        self.assertEqual(AuditEvent.objects.filter(event_type=AuditEvent.EventType.OPT_OUT_DETECTED).count(), 1)


class QueueAndSenderTests(MessagingSafetyTestCase):
    def test_initial_message_is_idempotent(self):
        first, first_created = enqueue_initial_message(self.member)
        second, second_created = enqueue_initial_message(self.member)
        self.assertTrue(first_created)
        self.assertFalse(second_created)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(Message.objects.count(), 1)

    def test_fake_sender_returns_fake_confirmation(self):
        result = FakeSender().send(self.make_ready_message())
        self.assertTrue(result.success)
        self.assertTrue(result.provider_message_id.startswith("fake-"))

    @override_settings(OPENCLAW_WHATSAPP_ACCOUNT_ID="academy")
    def test_openclaw_sender_returns_confirmed_whatsapp_id(self):
        from unittest.mock import patch

        message = self.make_ready_message(idempotency_key="initial-outreach:1")
        with patch("messaging.sender.OpenClawClient.send_whatsapp", return_value="wa-123") as send:
            result = OpenClawWhatsAppSender().send(message)

        self.assertTrue(result.success)
        self.assertEqual(result.provider_message_id, "wa-123")
        send.assert_called_once_with(
            target="+17845551234",
            message="Hi Carlos",
            idempotency_key="initial-outreach:1",
            account_id="academy",
        )


class FailingSender(BaseSender):
    def send(self, message):
        return SendResult(False, failure_reason="Simulated failure")


class WorkerTests(MessagingSafetyTestCase):
    def test_worker_queues_and_fake_sends_eligible_candidate(self):
        result = process_next(FakeSender())
        self.assertEqual(result.outcome, "sent")
        message = Message.objects.get(pk=result.message_id)
        self.assertEqual(message.status, Message.Status.SENT)
        self.assertTrue(message.provider_message_id.startswith("fake-"))
        self.member.refresh_from_db()
        self.candidate.refresh_from_db()
        self.assertEqual(self.member.messages_sent, 1)
        self.assertEqual(self.member.status, CampaignMember.Status.CONTACTED)
        self.assertEqual(self.candidate.status, Candidate.Status.CONTACTED)
        self.assertTrue(AuditEvent.objects.filter(event_type=AuditEvent.EventType.MESSAGE_APPROVED).exists())
        self.assertTrue(AuditEvent.objects.filter(event_type=AuditEvent.EventType.MESSAGE_SENT).exists())

    def test_worker_never_calls_sender_while_system_is_paused(self):
        class ExplodingSender(BaseSender):
            def send(self, message):
                raise AssertionError("Sender must not be called")

        set_outbound_enabled(False, reason="Emergency pause")
        result = process_next(ExplodingSender())
        self.assertEqual(result.outcome, "blocked")
        self.assertEqual(result.reason, PolicyReason.SYSTEM_PAUSED)
        self.assertEqual(Message.objects.count(), 0)

    def test_worker_cancels_existing_message_for_do_not_contact_candidate(self):
        message = self.make_ready_message()
        self.candidate.do_not_contact = True
        self.candidate.save(update_fields={"do_not_contact"})
        result = process_next(FakeSender())
        message.refresh_from_db()
        self.assertEqual(result.reason, PolicyReason.DO_NOT_CONTACT)
        self.assertEqual(message.status, Message.Status.CANCELLED)
        self.assertEqual(message.provider_message_id, "")

    def test_worker_records_sender_failure(self):
        message = self.make_ready_message()
        result = process_next(FailingSender())
        message.refresh_from_db()
        self.assertEqual(result.outcome, "failed")
        self.assertEqual(message.status, Message.Status.FAILED)
        self.assertEqual(message.retry_count, 1)
        self.assertEqual(message.failure_reason, "Simulated failure")

    def test_worker_defers_rate_limited_message_without_calling_sender(self):
        class ExplodingSender(BaseSender):
            def send(self, message):
                raise AssertionError("Sender must not be called")

        self.campaign.hourly_limit = 1
        self.campaign.min_message_interval_seconds = 0
        self.campaign.save(update_fields={"hourly_limit", "min_message_interval_seconds"})
        self.add_sent_message()
        message = self.make_ready_message()
        result = process_next(ExplodingSender())
        message.refresh_from_db()
        self.assertEqual(result.reason, PolicyReason.RATE_LIMIT_HOURLY)
        self.assertGreater(message.scheduled_at, self.now)
        self.assertEqual(message.status, Message.Status.READY)
