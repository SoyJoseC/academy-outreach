import json
import logging
from typing import Any

import httpx
from django.conf import settings

from .schemas import ADMISSIONS_DECISION_TOOL, AdmissionsRequest, AgentDecision

logger = logging.getLogger(__name__)


class OpenClawError(RuntimeError):
    pass


class OpenClawConfigurationError(OpenClawError):
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

    @property
    def responses_url(self) -> str:
        if not self.endpoint:
            raise OpenClawConfigurationError("OPENCLAW_ENDPOINT is not configured.")
        if self.endpoint.endswith("/v1/responses"):
            return self.endpoint
        return f"{self.endpoint}/v1/responses"

    def recommend(self, request: AdmissionsRequest) -> AgentDecision:
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
