import json
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any, Mapping


class AgentResponseValidationError(ValueError):
    pass


class AgentAction(StrEnum):
    SEND = "send"
    HUMAN_REVIEW = "human_review"
    SKIP = "skip"


@dataclass(frozen=True)
class CandidateContext:
    first_name: str
    country: str
    course_interest: str


@dataclass(frozen=True)
class CampaignContext:
    name: str
    objective: str


@dataclass(frozen=True)
class AdmissionsRequest:
    task: str
    candidate: CandidateContext
    campaign: CampaignContext

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AgentDecision:
    action: AgentAction
    message: str
    requires_human: bool
    reason: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action.value if isinstance(self.action, AgentAction) else self.action,
            "message": self.message,
            "requires_human": self.requires_human,
            "reason": self.reason,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "AgentDecision":
        required = {"action", "message", "requires_human", "reason"}
        if set(value) != required:
            raise AgentResponseValidationError("Agent response fields do not match the required schema.")
        try:
            action = AgentAction(value["action"])
        except (TypeError, ValueError) as exc:
            raise AgentResponseValidationError("Agent action is not supported.") from exc
        if not isinstance(value["message"], str):
            raise AgentResponseValidationError("Agent message must be a string.")
        message = value["message"].strip()
        if len(message) > 2000:
            raise AgentResponseValidationError("Agent message exceeds 2000 characters.")
        if type(value["requires_human"]) is not bool:
            raise AgentResponseValidationError("requires_human must be a boolean.")
        reason = value["reason"]
        if reason is not None and not isinstance(reason, str):
            raise AgentResponseValidationError("Agent reason must be a string or null.")
        reason = reason.strip() if isinstance(reason, str) else None
        if reason and len(reason) > 1000:
            raise AgentResponseValidationError("Agent reason exceeds 1000 characters.")

        if action == AgentAction.SEND and (not message or value["requires_human"]):
            raise AgentResponseValidationError("send requires a message and cannot require human review.")
        if action == AgentAction.HUMAN_REVIEW and (not value["requires_human"] or not reason):
            raise AgentResponseValidationError("human_review requires requires_human=true and a reason.")
        if action == AgentAction.SKIP and value["requires_human"]:
            raise AgentResponseValidationError("skip cannot require human review.")

        return cls(action=action, message=message, requires_human=value["requires_human"], reason=reason)

    @classmethod
    def from_json(cls, value: str) -> "AgentDecision":
        try:
            decoded = json.loads(value)
        except (TypeError, json.JSONDecodeError) as exc:
            raise AgentResponseValidationError("Agent arguments are not valid JSON.") from exc
        if not isinstance(decoded, dict):
            raise AgentResponseValidationError("Agent arguments must be a JSON object.")
        return cls.from_mapping(decoded)


ADMISSIONS_DECISION_TOOL = {
    "type": "function",
    "name": "admissions_decision",
    "description": "Return the recommended admissions action. Django will independently decide whether sending is allowed.",
    "parameters": {
        "type": "object",
        "additionalProperties": False,
        "required": ["action", "message", "requires_human", "reason"],
        "properties": {
            "action": {"type": "string", "enum": [action.value for action in AgentAction]},
            "message": {"type": "string", "maxLength": 2000},
            "requires_human": {"type": "boolean"},
            "reason": {"type": ["string", "null"], "maxLength": 1000},
        },
    },
}
