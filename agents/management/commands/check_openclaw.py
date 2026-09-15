from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from agents.openclaw import OpenClawClient, OpenClawError
from agents.schemas import AdmissionsRequest, CampaignContext, CandidateContext


class Command(BaseCommand):
    help = "Check OpenClaw Gateway liveness and optionally its structured admissions contract."

    def add_arguments(self, parser):
        parser.add_argument(
            "--health-only",
            action="store_true",
            help="Check the inexpensive /health probe without calling the model.",
        )

    def handle(self, *args, **options):
        if not settings.OPENCLAW_ENDPOINT:
            raise CommandError("OPENCLAW_ENDPOINT is not configured.")
        if not settings.OPENCLAW_AUTH_TOKEN:
            raise CommandError(
                "OPENCLAW_AUTH_TOKEN is required by this project's secure Gateway baseline."
            )
        client = OpenClawClient()
        try:
            client.check_health()
            self.stdout.write(self.style.SUCCESS("OpenClaw Gateway liveness: PASS"))
            if options["health_only"]:
                return

            decision = client.recommend(
                AdmissionsRequest(
                    task="integration_smoke_test",
                    candidate=CandidateContext(
                        first_name="Test",
                        country="",
                        course_interest="",
                    ),
                    campaign=CampaignContext(
                        name="Integration smoke test",
                        objective="Validate the structured admissions response contract only.",
                    ),
                )
            )
        except OpenClawError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"OpenClaw structured contract: PASS (validated action={decision.action.value})"
            )
        )
        self.stdout.write("No candidate, campaign, message, or sender was used.")
