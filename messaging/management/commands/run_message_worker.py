import time

from django.conf import settings
from django.core.management.base import BaseCommand

from messaging.worker import process_next


class Command(BaseCommand):
    help = "Process outbound messages using the configured sender (FakeSender by default)."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Run one worker iteration and exit.")
        parser.add_argument("--max-messages", type=int, help="Exit after this many successful sends.")
        parser.add_argument("--poll-seconds", type=float, default=settings.MESSAGE_WORKER_POLL_SECONDS)

    def handle(self, *args, **options):
        sent = 0
        while True:
            result = process_next()
            self.stdout.write(
                f"outcome={result.outcome} message_id={result.message_id or '-'} reason={result.reason or '-'}"
            )
            if result.outcome == "sent":
                sent += 1
            if options["once"] or (options["max_messages"] and sent >= options["max_messages"]):
                return
            time.sleep(max(options["poll_seconds"], 0.1))
