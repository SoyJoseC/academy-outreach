import json

import httpx
from django.test import TestCase

from audit.models import AuditEvent
from campaigns.models import Campaign, CampaignMember
from candidates.models import Candidate
from messaging.models import Message
from messaging.sender import BaseSender
from messaging.worker import process_next

from .openclaw import OpenClawClient, OpenClawConfigurationError, OpenClawError
from .schemas import (
    AdmissionsRequest,
    AgentAction,
    AgentDecision,
    AgentResponseValidationError,
    CampaignContext,
    CandidateContext,
)
from .services import BaseAdmissionsAgent, GenerationOutcome, generate_pending_message


def sample_request():
    return AdmissionsRequest(
        task="initial_outreach",
        candidate=CandidateContext("Carlos", "Saint Vincent and the Grenadines", "Web Development"),
        campaign=CampaignContext("September Admissions", "Confirm current interest"),
    )


class AgentSchemaTests(TestCase):
    def test_valid_send_response(self):
        decision = AgentDecision.from_mapping(
            {"action": "send", "message": "Hi Carlos", "requires_human": False, "reason": None}
        )
        self.assertEqual(decision.action, AgentAction.SEND)

    def test_unknown_action_is_rejected(self):
        with self.assertRaises(AgentResponseValidationError):
            AgentDecision.from_mapping(
                {"action": "send_now", "message": "Hi", "requires_human": False, "reason": None}
            )

    def test_send_requires_nonempty_message(self):
        with self.assertRaises(AgentResponseValidationError):
            AgentDecision.from_mapping(
                {"action": "send", "message": " ", "requires_human": False, "reason": None}
            )

    def test_human_review_requires_reason_and_flag(self):
        with self.assertRaises(AgentResponseValidationError):
            AgentDecision.from_mapping(
                {"action": "human_review", "message": "", "requires_human": False, "reason": None}
            )

    def test_extra_fields_are_rejected(self):
        with self.assertRaises(AgentResponseValidationError):
            AgentDecision.from_mapping(
                {
                    "action": "skip",
                    "message": "",
                    "requires_human": False,
                    "reason": "Not appropriate",
                    "send_directly": True,
                }
            )


class OpenClawClientTests(TestCase):
    def test_health_check_uses_dedicated_gateway_endpoint(self):
        observed = {}

        def handler(request):
            observed["method"] = request.method
            observed["url"] = str(request.url)
            return httpx.Response(200, json={"ok": True, "status": "live"})

        client = OpenClawClient(
            endpoint="https://gateway.test:18789/v1/responses",
            token="test-token",
            transport=httpx.MockTransport(handler),
        )
        client.check_health()
        self.assertEqual(observed, {"method": "GET", "url": "https://gateway.test:18789/health"})

    def test_unhealthy_gateway_response_is_rejected(self):
        client = OpenClawClient(
            endpoint="https://gateway.test:18789",
            token="test-token",
            transport=httpx.MockTransport(
                lambda request: httpx.Response(503, json={"ok": False, "status": "starting"})
            ),
        )
        with self.assertRaises(OpenClawError):
            client.check_health()

    def test_client_uses_official_responses_endpoint_and_required_tool_call(self):
        observed = {}

        def handler(request):
            observed["url"] = str(request.url)
            observed["authorization"] = request.headers.get("Authorization")
            observed["agent"] = request.headers.get("x-openclaw-agent-id")
            observed["payload"] = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "status": "completed",
                    "output": [
                        {
                            "type": "function_call",
                            "name": "admissions_decision",
                            "arguments": json.dumps(
                                {
                                    "action": "send",
                                    "message": "Hi Carlos",
                                    "requires_human": False,
                                    "reason": None,
                                }
                            ),
                        }
                    ],
                },
            )

        client = OpenClawClient(
            endpoint="https://gateway.test:18789",
            token="test-token",
            agent_id="academy-admissions",
            model="openclaw/academy-admissions",
            transport=httpx.MockTransport(handler),
        )
        decision = client.recommend(sample_request())
        self.assertEqual(decision.action, AgentAction.SEND)
        self.assertEqual(observed["url"], "https://gateway.test:18789/v1/responses")
        self.assertEqual(observed["authorization"], "Bearer test-token")
        self.assertEqual(observed["agent"], "academy-admissions")
        self.assertEqual(observed["payload"]["tool_choice"]["name"], "admissions_decision")
        structured_input = json.loads(observed["payload"]["input"])
        self.assertEqual(structured_input["candidate"]["first_name"], "Carlos")

    def test_missing_token_is_rejected(self):
        client = OpenClawClient(endpoint="https://gateway.test", token="")
        with self.assertRaises(OpenClawConfigurationError):
            client.validate_configuration()

    def test_public_http_endpoint_is_rejected(self):
        client = OpenClawClient(endpoint="http://gateway.example.com", token="test-token")
        with self.assertRaises(OpenClawConfigurationError):
            client.validate_configuration()

    def test_private_http_endpoint_is_allowed(self):
        client = OpenClawClient(endpoint="http://127.0.0.1:18789", token="test-token")
        client.validate_configuration()

    def test_whatsapp_send_uses_message_tool_and_idempotency(self):
        observed = {}

        def handler(request):
            observed["url"] = str(request.url)
            observed["headers"] = request.headers
            observed["payload"] = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "result": {
                        "content": [{"type": "text", "text": "sent"}],
                        "details": {"messageId": "wa-message-123"},
                    },
                },
            )

        client = OpenClawClient(
            endpoint="https://gateway.test",
            token="test-token",
            agent_id="academy-admissions",
            transport=httpx.MockTransport(handler),
        )
        provider_id = client.send_whatsapp(
            target="+17845551234",
            message="Hi Carlos",
            idempotency_key="initial-outreach:42",
            account_id="academy",
        )

        self.assertEqual(provider_id, "wa-message-123")
        self.assertEqual(observed["url"], "https://gateway.test/tools/invoke")
        self.assertEqual(observed["headers"]["authorization"], "Bearer test-token")
        self.assertEqual(observed["headers"]["x-openclaw-message-channel"], "whatsapp")
        self.assertEqual(observed["payload"]["tool"], "message")
        self.assertEqual(observed["payload"]["args"]["target"], "+17845551234")
        self.assertEqual(observed["payload"]["args"]["idempotencyKey"], "initial-outreach:42")

    def test_whatsapp_send_without_provider_id_fails_closed(self):
        client = OpenClawClient(
            endpoint="https://gateway.test",
            token="test-token",
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json={"ok": True, "result": {"details": {}}})
            ),
        )
        with self.assertRaises(OpenClawError):
            client.send_whatsapp(
                target="+17845551234",
                message="Hi",
                idempotency_key="initial-outreach:42",
            )

    def test_missing_structured_tool_call_is_rejected(self):
        with self.assertRaises(OpenClawError):
            OpenClawClient._parse_response(
                {"status": "completed", "output": [{"type": "message", "content": "send it"}]}
            )

    def test_malformed_tool_arguments_are_rejected(self):
        with self.assertRaises(AgentResponseValidationError):
            OpenClawClient._parse_response(
                {
                    "status": "completed",
                    "output": [
                        {"type": "function_call", "name": "admissions_decision", "arguments": "not-json"}
                    ],
                }
            )

    def test_failed_response_is_rejected(self):
        with self.assertRaises(OpenClawError):
            OpenClawClient._parse_response({"status": "failed", "output": []})

    def test_additional_function_call_is_rejected(self):
        decision = {
            "type": "function_call",
            "name": "admissions_decision",
            "arguments": json.dumps(
                {"action": "skip", "message": "", "requires_human": False, "reason": None}
            ),
        }
        with self.assertRaises(OpenClawError):
            OpenClawClient._parse_response(
                {"status": "completed", "output": [decision, {"type": "function_call", "name": "other"}]}
            )


class StaticAgent(BaseAdmissionsAgent):
    def __init__(self, decision):
        self.decision = decision

    def recommend(self, request):
        return self.decision


class RaisingAgent(BaseAdmissionsAgent):
    def recommend(self, request):
        raise AgentResponseValidationError("Malformed OpenClaw response")


class AgentServiceTests(TestCase):
    def setUp(self):
        self.candidate = Candidate.objects.create(
            first_name="Carlos",
            phone="+17845551234",
            country="Saint Vincent and the Grenadines",
            course_interest="Web Development",
            status=Candidate.Status.READY,
        )
        self.campaign = Campaign.objects.create(
            name="September Admissions",
            description="Confirm current interest",
            status=Campaign.Status.ACTIVE,
        )
        self.member = CampaignMember.objects.create(campaign=self.campaign, candidate=self.candidate)
        self.message = Message.objects.create(
            candidate=self.candidate,
            campaign=self.campaign,
            campaign_member=self.member,
            direction=Message.Direction.OUTBOUND,
            status=Message.Status.PENDING,
            idempotency_key=f"initial-outreach:{self.member.pk}",
        )

    def test_valid_send_becomes_ready(self):
        agent = StaticAgent(AgentDecision(AgentAction.SEND, "Hi Carlos", False, None))
        result = generate_pending_message(self.message, agent=agent)
        self.message.refresh_from_db()
        self.assertEqual(result.outcome, GenerationOutcome.READY)
        self.assertEqual(self.message.status, Message.Status.READY)
        self.assertEqual(self.message.content, "Hi Carlos")
        self.assertIsNotNone(self.message.generated_at)

    def test_human_review_locks_campaign_member(self):
        agent = StaticAgent(
            AgentDecision(
                AgentAction.HUMAN_REVIEW,
                "",
                True,
                "Candidate requested a custom payment arrangement",
            )
        )
        result = generate_pending_message(self.message, agent=agent)
        self.message.refresh_from_db()
        self.member.refresh_from_db()
        self.assertEqual(result.outcome, GenerationOutcome.HUMAN_REVIEW)
        self.assertEqual(self.message.status, Message.Status.REQUIRES_HUMAN)
        self.assertTrue(self.member.human_required)
        self.assertTrue(AuditEvent.objects.filter(event_type=AuditEvent.EventType.HUMAN_ESCALATION).exists())

    def test_skip_cancels_message_and_member(self):
        agent = StaticAgent(AgentDecision(AgentAction.SKIP, "", False, "No relevant course interest"))
        result = generate_pending_message(self.message, agent=agent)
        self.message.refresh_from_db()
        self.member.refresh_from_db()
        self.assertEqual(result.outcome, GenerationOutcome.SKIPPED)
        self.assertEqual(self.message.status, Message.Status.CANCELLED)
        self.assertEqual(self.member.status, CampaignMember.Status.SKIPPED)

    def test_malformed_agent_response_fails_closed(self):
        result = generate_pending_message(self.message, agent=RaisingAgent())
        self.message.refresh_from_db()
        self.assertEqual(result.outcome, GenerationOutcome.FAILED)
        self.assertEqual(self.message.status, Message.Status.FAILED)
        self.assertEqual(self.message.provider_message_id, "")
        self.assertTrue(AuditEvent.objects.filter(event_type=AuditEvent.EventType.AGENT_ERROR).exists())

    def test_semantically_invalid_typed_decision_also_fails_closed(self):
        invalid = AgentDecision(AgentAction.SEND, "Hi Carlos", True, None)
        result = generate_pending_message(self.message, agent=StaticAgent(invalid))
        self.message.refresh_from_db()
        self.assertEqual(result.outcome, GenerationOutcome.FAILED)
        self.assertEqual(self.message.status, Message.Status.FAILED)

    def test_worker_stops_at_human_review_without_sender(self):
        class ExplodingSender(BaseSender):
            def send(self, message):
                raise AssertionError("Sender must not be called")

        agent = StaticAgent(AgentDecision(AgentAction.HUMAN_REVIEW, "", True, "Needs operator"))
        result = process_next(ExplodingSender(), agent)
        self.assertEqual(result.outcome, GenerationOutcome.HUMAN_REVIEW)
        self.message.refresh_from_db()
        self.assertEqual(self.message.status, Message.Status.REQUIRES_HUMAN)

    def test_worker_checks_do_not_contact_before_calling_agent(self):
        class ExplodingAgent(BaseAdmissionsAgent):
            def recommend(self, request):
                raise AssertionError("Agent must not be called")

        self.candidate.do_not_contact = True
        self.candidate.save(update_fields={"do_not_contact"})
        result = process_next(agent=ExplodingAgent())
        self.message.refresh_from_db()
        self.assertEqual(result.reason, "DO_NOT_CONTACT")
        self.assertEqual(self.message.status, Message.Status.CANCELLED)
