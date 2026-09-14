from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
import phonenumbers


class PhoneNormalizationError(ValueError):
    """Raised when a phone number cannot be safely normalized to E.164."""


def normalize_phone(value: str, *, default_region: str | None = None) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""

    region = (default_region or settings.DEFAULT_PHONE_REGION or "").upper() or None
    try:
        parsed = phonenumbers.parse(raw, None if raw.startswith("+") else region)
    except phonenumbers.NumberParseException as exc:
        raise PhoneNormalizationError("Phone number could not be parsed.") from exc

    if not phonenumbers.is_possible_number(parsed) or not phonenumbers.is_valid_number(parsed):
        raise PhoneNormalizationError("Phone number is not valid.")

    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


def normalize_email(value: str) -> str:
    email = (value or "").strip().lower()
    if not email:
        return ""
    try:
        validate_email(email)
    except ValidationError as exc:
        raise ValueError("Email address is not valid.") from exc
    return email

