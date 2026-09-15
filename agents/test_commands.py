import json

import httpx
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings

from agents.openclaw import OpenClawClient


class CheckOpenClawCommandTests(SimpleTestCase):
    @override_settings(OPENCLAW_ENDPOINT="", OPENCLAW_AUTH_TOKEN="")
    def test_missing_configuration_fails_closed(self):
        with self.assertRaisesMessage(CommandError, "OPENCLAW_ENDPOINT is not configured"):
            call_command("check_openclaw")

    @override_settings(
        OPENCLAW_ENDPOINT="https://gateway.test:18789",
        OPENCLAW_AUTH_TOKEN="test-token",
        MESSAGE_SENDER_BACKEND="messaging.sender.FakeSender",
    )
    def test_health_only_never_calls_responses_endpoint(self):
        requests = []

        def handler(request):
            requests.append(str(request.url))
            return httpx.Response(200, json={"ok": True, "status": "live"})

        original_init = OpenClawClient.__init__

        def patched_init(instance):
            original_init(instance, transport=httpx.MockTransport(handler))

        from unittest.mock import patch

        with patch.object(OpenClawClient, "__init__", patched_init):
            call_command("check_openclaw", health_only=True)
        self.assertEqual(requests, ["https://gateway.test:18789/health"])

    @override_settings(
        OPENCLAW_ENDPOINT="https://gateway.test:18789",
        OPENCLAW_AUTH_TOKEN="test-token",
        MESSAGE_SENDER_BACKEND="messaging.sender.FakeSender",
    )
    def test_full_smoke_test_validates_structured_contract(self):
        requests = []

        def handler(request):
            requests.append(request)
            if request.url.path == "/health":
                return httpx.Response(200, json={"ok": True, "status": "live"})
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
                                    "action": "human_review",
                                    "message": "",
                                    "requires_human": True,
                                    "reason": "No approved academy facts are configured.",
                                }
                            ),
                        }
                    ],
                },
            )

        original_init = OpenClawClient.__init__

        def patched_init(instance):
            original_init(instance, transport=httpx.MockTransport(handler))

        from unittest.mock import patch

        with patch.object(OpenClawClient, "__init__", patched_init):
            call_command("check_openclaw")

        self.assertEqual([request.url.path for request in requests], ["/health", "/v1/responses"])
        self.assertEqual(requests[1].headers["authorization"], "Bearer test-token")
