import csv
from dataclasses import asdict, dataclass, field
from typing import TextIO

from django.db import transaction
from django.db.models import Q

from audit.models import AuditEvent
from campaigns.models import Campaign, CampaignMember
from candidates.models import Candidate
from candidates.normalization import PhoneNormalizationError, normalize_email, normalize_phone


REQUIRED_COLUMNS = {
    "first_name",
    "last_name",
    "phone",
    "email",
    "country",
    "course_interest",
}


class CSVImportError(ValueError):
    """Raised when the CSV itself cannot be processed."""


@dataclass(frozen=True)
class RowError:
    row: int
    reason: str


@dataclass
class ImportReport:
    imported: int = 0
    updated: int = 0
    skipped: int = 0
    duplicates: int = 0
    invalid: int = 0
    do_not_contact: int = 0
    errors: list[RowError] = field(default_factory=list)

    @property
    def processed(self) -> int:
        return (
            self.imported
            + self.updated
            + self.skipped
            + self.duplicates
            + self.invalid
            + self.do_not_contact
        )

    def audit_metadata(self) -> dict:
        data = asdict(self)
        data["processed"] = self.processed
        return data


def _clean_text(value: str | None) -> str:
    return (value or "").strip()


def _find_existing_candidate(phone: str, email: str) -> Candidate | None:
    lookup = Q(phone=phone)
    if email:
        lookup |= Q(email=email)
    matches = list(Candidate.objects.filter(lookup).order_by("id")[:2])
    if len(matches) > 1:
        raise CSVImportError("Phone and email belong to different existing candidates.")
    return matches[0] if matches else None


def _audit(event_type: str, *, candidate: Candidate | None = None, metadata: dict | None = None) -> None:
    AuditEvent.objects.create(
        event_type=event_type,
        entity_type="Candidate" if candidate else "",
        entity_id=str(candidate.pk) if candidate else "",
        metadata=metadata or {},
    )


def import_candidates_csv(
    stream: TextIO,
    *,
    campaign: Campaign,
    default_phone_region: str | None = None,
    source: str = "CSV",
) -> ImportReport:
    reader = csv.DictReader(stream)
    if not reader.fieldnames:
        raise CSVImportError("CSV file has no header row.")

    reader.fieldnames = [header.strip() if header else "" for header in reader.fieldnames]
    normalized_headers = {header for header in reader.fieldnames if header}
    if len(normalized_headers) != len([header for header in reader.fieldnames if header]):
        raise CSVImportError("CSV header contains duplicate columns.")
    missing = sorted(REQUIRED_COLUMNS - normalized_headers)
    if missing:
        raise CSVImportError(f"Missing required columns: {', '.join(missing)}")

    report = ImportReport()
    seen_phones: set[str] = set()
    seen_emails: set[str] = set()

    for row_number, row in enumerate(reader, start=2):
        try:
            first_name = _clean_text(row.get("first_name"))
            if not first_name:
                raise ValueError("First name is required.")

            phone = normalize_phone(row.get("phone", ""), default_region=default_phone_region)
            if not phone:
                raise ValueError("A valid phone number is required.")
            email = normalize_email(row.get("email", ""))

            if phone in seen_phones or (email and email in seen_emails):
                report.duplicates += 1
                report.errors.append(RowError(row_number, "Duplicate row in CSV."))
                _audit(
                    AuditEvent.EventType.DUPLICATE_DETECTED,
                    metadata={"row": row_number, "phone": phone, "email": email},
                )
                continue

            seen_phones.add(phone)
            if email:
                seen_emails.add(email)

            with transaction.atomic():
                candidate = _find_existing_candidate(phone, email)
                if candidate and candidate.do_not_contact:
                    report.do_not_contact += 1
                    report.errors.append(RowError(row_number, "Candidate is marked do not contact."))
                    continue

                if candidate and CampaignMember.objects.filter(campaign=campaign, candidate=candidate).exists():
                    report.skipped += 1
                    report.errors.append(RowError(row_number, "Candidate is already in this campaign."))
                    continue

                values = {
                    "first_name": first_name,
                    "last_name": _clean_text(row.get("last_name")),
                    "phone": phone,
                    "email": email,
                    "country": _clean_text(row.get("country")),
                    "course_interest": _clean_text(row.get("course_interest")),
                    "source": source,
                }

                if candidate:
                    for field_name, value in values.items():
                        setattr(candidate, field_name, value)
                    if candidate.status in {Candidate.Status.NEW, Candidate.Status.INVALID}:
                        candidate.status = Candidate.Status.READY
                    candidate.save()
                    report.updated += 1
                    _audit(AuditEvent.EventType.CANDIDATE_UPDATED, candidate=candidate)
                else:
                    candidate = Candidate.objects.create(**values, status=Candidate.Status.READY)
                    report.imported += 1
                    _audit(AuditEvent.EventType.CANDIDATE_CREATED, candidate=candidate)

                CampaignMember.objects.create(campaign=campaign, candidate=candidate)
                _audit(
                    AuditEvent.EventType.CAMPAIGN_MEMBER_CREATED,
                    candidate=candidate,
                    metadata={"campaign_id": campaign.pk},
                )

        except (PhoneNormalizationError, ValueError, CSVImportError) as exc:
            report.invalid += 1
            report.errors.append(RowError(row_number, str(exc)))

    AuditEvent.objects.create(
        event_type=AuditEvent.EventType.CSV_IMPORTED,
        entity_type="Campaign",
        entity_id=str(campaign.pk),
        metadata=report.audit_metadata(),
    )
    return report
