import json
import logging
from ipaddress import ip_address, ip_network
from typing import Any
from urllib.parse import urlparse

import httpx
from django.conf import settings

from .schemas import ADMISSIONS_DECISION_TOOL, AdmissionsRequest, AgentDecision

logger = logging.getLogger(__name__)


class OpenClawError(RuntimeError):
    pass


class OpenClawConfigurationError(OpenClawError):
    pass


class OpenClawDeliveryError(OpenClawError):
    pass


class OpenClawClient:
    """Small client for OpenClaw's OpenResponses-compatible HTTP endpoint."""

    def __init__(
        self,
        *,
        endpoint: str | None = None,
        token: str | None = None,
        agent_id: str | None = None,
        model: str | None = None,
        timeout: float | None = None,
        transport: httpx.BaseTransport | None = None,
    ):
        self.endpoint = (endpoint if endpoint is not None else settings.OPENCLAW_ENDPOINT).rstrip("/")
        self.token = token if token is not None else settings.OPENCLAW_AUTH_TOKEN
        self.agent_id = agent_id if agent_id is not None else settings.OPENCLAW_AGENT_ID
        self.model = model if model is not None else settings.OPENCLAW_MODEL
        self.timeout = timeout if timeout is not None else settings.OPENCLAW_TIMEOUT_SECONDS
        self.transport = transport

    def validate_configuration(self) -> None:
        if not self.endpoint:
            raise OpenClawConfigurationError("OPENCLAW_ENDPOINT is not configured.")
        if not self.token:
            raise OpenClawConfigurationError(
                "OPENCLAW_AUTH_TOKEN is required by this project's secure Gateway baseline."
            )
        parsed = urlparse(self.endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise OpenClawConfigurationError("OPENCLAW_ENDPOINT must be a valid HTTP(S) URL.")
        if parsed.username or parsed.password:
            raise OpenClawConfigurationError("OPENCLAW_ENDPOINT must not contain credentials.")
        if parsed.scheme == "http" and not self._is_private_host(parsed.hostname):
            raise OpenClawConfigurationError(
                "Public OpenClaw endpoints must use HTTPS; HTTP is allowed only on private networks."
            )

    @staticmethod
    def _is_private_host(hostname: str) -> bool:
        hostname = hostname.rstrip(".").lower()
        if hostname == "localhost" or hostname.endswith((".local", ".ts.net")):
            return True
        try:
            address = ip_address(hostname)
        except ValueError:
            return False
        carrier_grade_nat = ip_network("100.64.0.0/10")
        return (
            address.is_loopback
            or address.is_private
            or address.is_link_local
            or address in carrier_grade_nat
        )

    @property
    def responses_url(self) -> str:
        if not self.endpoint:
            raise OpenClawConfigurationError("OPENCLAW_ENDPOINT is not configured.")
        if self.endpoint.endswith("/v1/responses"):
            return self.endpoint
        return f"{self.endpoint}/v1/responses"

    @property
    def health_url(self) -> str:
        if not self.endpoint:
            raise OpenClawConfigurationError("OPENCLAW_ENDPOINT is not configured.")
        if self.endpoint.endswith("/v1/responses"):
            return f"{self.endpoint[:-len('/v1/responses')]}/health"
        return f"{self.endpoint}/health"

    @property
    def tools_url(self) -> str:
        if not self.endpoint:
            raise OpenClawConfigurationError("OPENCLAW_ENDPOINT is not configured.")
        base = (
            self.endpoint[: -len("/v1/responses")]
            if self.endpoint.endswith("/v1/responses")
            else self.endpoint
        )
        return f"{base}/tools/invoke"

    def check_health(self) -> None:
        """Verify Gateway HTTP liveness without creating an agent session."""
        self.validate_configuration()
        try:
            with httpx.Client(transport=self.transport, timeout=self.timeout) as client:
                response = client.get(self.health_url)
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise OpenClawError("OpenClaw health check failed or returned invalid JSON.") from exc
        if not isinstance(data, dict) or data.get("ok") is not True or data.get("status") != "live":
            raise OpenClawError("OpenClaw health response did not report a live Gateway.")

    def recommend(self, request: AdmissionsRequest) -> AgentDecision:
        self.validate_configuration()
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if self.agent_id:
            headers["x-openclaw-agent-id"] = self.agent_id
        payload = {
            "model": self.model,
            "stream": False,
            "instructions": (
                "Use the academy-admissions skill and approved knowledge only. "
                "Return exactly one admissions_decision tool call."
            ),
            "input": json.dumps(request.to_dict(), ensure_ascii=False),
            "tools": [ADMISSIONS_DECISION_TOOL],
            "tool_choice": {"type": "function", "name": "admissions_decision"},
        }
        logger.info("OpenClaw request task=%s", request.task)
        try:
            with httpx.Client(transport=self.transport, timeout=self.timeout) as client:
                response = client.post(self.responses_url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise OpenClawError("OpenClaw request failed or returned invalid JSON.") from exc
        return self._parse_response(data)

    def send_whatsapp(
        self,
        *,
        target: str,
        message: str,
        idempotency_key: str,
        account_id: str = "default",
    ) -> str:
        """Send one already-approved message through OpenClaw's message tool."""
        self.validate_configuration()
        account_id = account_id.strip()
        if not account_id:
            raise OpenClawDeliveryError("OpenClaw WhatsApp account ID must not be empty.")
        if not target.startswith("+") or not target[1:].isdigit():
            raise OpenClawDeliveryError("WhatsApp target must be an E.164 phone number.")
        if not message.strip():
            raise OpenClawDeliveryError("WhatsApp message must not be empty.")
        if not idempotency_key.strip():
            raise OpenClawDeliveryError("WhatsApp delivery requires an idempotency key.")

        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "x-openclaw-message-channel": "whatsapp",
            "x-openclaw-message-to": target,
            "x-openclaw-account-id": account_id,
        }
        args = {
            "action": "send",
            "channel": "whatsapp",
            "target": target,
            "message": message,
            "accountId": account_id,
            "idempotencyKey": idempotency_key,
        }
        payload = {
            "tool": "message",
            "action": "send",
            "args": args,
            "agentId": self.agent_id,
            "idempotencyKey": idempotency_key,
            "dryRun": False,
        }
        try:
            with httpx.Client(transport=self.transport, timeout=self.timeout) as client:
                response = client.post(self.tools_url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise OpenClawDeliveryError(
                "OpenClaw WhatsApp delivery failed or returned invalid JSON."
            ) from exc
        return self._parse_delivery_response(data)

    @staticmethod
    def _parse_delivery_response(data: Any) -> str:
        if not isinstance(data, dict) or data.get("ok") is not True:
            error = data.get("error") if isinstance(data, dict) else None
            reason = error.get("message") if isinstance(error, dict) else None
            raise OpenClawDeliveryError(reason or "OpenClaw rejected WhatsApp delivery.")
        result = data.get("result")
        details = result.get("details") if isinstance(result, dict) else None
        if not isinstance(details, dict):
            raise OpenClawDeliveryError("OpenClaw delivery response has no details object.")
        provider_id = details.get("messageId")
        if not provider_id and isinstance(details.get("result"), dict):
            provider_id = details["result"].get("messageId")
        if not isinstance(provider_id, str) or not provider_id.strip():
            raise OpenClawDeliveryError("OpenClaw did not confirm a WhatsApp message ID.")
        return provider_id.strip()

    @staticmethod
    def _parse_response(data: Any) -> AgentDecision:
        if not isinstance(data, dict) or data.get("status") != "completed":
            raise OpenClawError("OpenClaw response did not complete successfully.")
        output = data.get("output")
        if not isinstance(output, list):
            raise OpenClawError("OpenClaw response has no output list.")
        calls = [item for item in output if isinstance(item, dict) and item.get("type") == "function_call"]
        if len(calls) != 1 or calls[0].get("name") != "admissions_decision":
            raise OpenClawError("OpenClaw must return exactly one admissions_decision call.")
        arguments = calls[0].get("arguments")
        if isinstance(arguments, dict):
            return AgentDecision.from_mapping(arguments)
        return AgentDecision.from_json(arguments)
