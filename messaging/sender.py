import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from uuid import uuid4

from django.conf import settings
from django.utils.module_loading import import_string

from .models import Message

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SendResult:
    success: bool
    provider_message_id: str = ""
    failure_reason: str = ""


class BaseSender(ABC):
    @abstractmethod
    def send(self, message: Message) -> SendResult:
        raise NotImplementedError


class FakeSender(BaseSender):
    """Safe development sender. It never contacts an external service."""

    def send(self, message: Message) -> SendResult:
        provider_id = f"fake-{uuid4()}"
        logger.info(
            "FAKE SEND candidate_id=%s campaign_id=%s message_id=%s content=%r",
            message.candidate_id,
            message.campaign_id,
            message.pk,
            message.content,
        )
        return SendResult(success=True, provider_message_id=provider_id)


class OpenClawWhatsAppSender(BaseSender):
    def send(self, message: Message) -> SendResult:
        raise RuntimeError("Real WhatsApp sending is disabled until a later milestone.")


def get_sender() -> BaseSender:
    sender_class = import_string(settings.MESSAGE_SENDER_BACKEND)
    sender = sender_class()
    if not isinstance(sender, BaseSender):
        raise TypeError("MESSAGE_SENDER_BACKEND must implement BaseSender.")
    return sender
