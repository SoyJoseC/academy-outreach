import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from campaigns.models import Campaign
from integrations.csv_import import CSVImportError, import_candidates_csv


class Command(BaseCommand):
    help = "Import candidates from CSV and associate eligible records with a campaign."

    def add_arguments(self, parser):
        parser.add_argument("csv_file", type=Path)
        parser.add_argument("--campaign", type=int, required=True, dest="campaign_id")
        parser.add_argument("--default-region", dest="default_region")

    def handle(self, *args, **options):
        path: Path = options["csv_file"]
        try:
            campaign = Campaign.objects.get(pk=options["campaign_id"])
        except Campaign.DoesNotExist as exc:
            raise CommandError("Campaign does not exist.") from exc

        if not path.is_file():
            raise CommandError(f"CSV file does not exist: {path}")

        try:
            with path.open("r", encoding="utf-8-sig", newline="") as stream:
                report = import_candidates_csv(
                    stream,
                    campaign=campaign,
                    default_phone_region=options.get("default_region"),
                )
        except (CSVImportError, UnicodeDecodeError, OSError) as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(json.dumps(report.audit_metadata(), indent=2))
        self.stdout.write(self.style.SUCCESS(f"Processed {report.processed} candidate row(s)."))

