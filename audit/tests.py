from django.test import TestCase

from .models import AuditEvent


class AuditEventTests(TestCase):
    def test_metadata_is_isolated_per_event(self):
        first = AuditEvent.objects.create(event_type=AuditEvent.EventType.CANDIDATE_CREATED)
        second = AuditEvent.objects.create(event_type=AuditEvent.EventType.MESSAGE_BLOCKED)
        first.metadata["candidate_id"] = 1
        self.assertEqual(second.metadata, {})

