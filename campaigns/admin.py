from io import StringIO

from django.conf import settings
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.urls import path, reverse
from django.utils.html import format_html

from integrations.csv_import import CSVImportError, import_candidates_csv
from integrations.forms import CandidateCSVUploadForm

from .models import Campaign, CampaignMember


class CampaignMemberInline(admin.TabularInline):
    model = CampaignMember
    extra = 0
    autocomplete_fields = ("candidate",)
    fields = ("candidate", "status", "messages_sent", "replies_received", "human_required")
    readonly_fields = ("messages_sent", "replies_received")


@admin.register(Campaign)
class CampaignAdmin(admin.ModelAdmin):
    list_display = ("name", "status", "start_at", "end_at", "hourly_limit", "daily_limit", "updated_at")
    list_filter = ("status", "created_at")
    search_fields = ("name", "description")
    readonly_fields = ("import_candidates_link", "created_at", "updated_at")
    inlines = (CampaignMemberInline,)
    actions = ("activate_campaigns", "pause_campaigns")

    def get_urls(self):
        custom_urls = [
            path(
                "<int:campaign_id>/import-candidates/",
                self.admin_site.admin_view(self.import_candidates_view),
                name="campaigns_campaign_import_candidates",
            )
        ]
        return custom_urls + super().get_urls()

    @admin.display(description="Candidate import")
    def import_candidates_link(self, obj: Campaign | None):
        if not obj or not obj.pk:
            return "Save the campaign before importing candidates."
        url = reverse("admin:campaigns_campaign_import_candidates", args=(obj.pk,))
        return format_html('<a class="button" href="{}">Import candidates from CSV</a>', url)

    def import_candidates_view(self, request: HttpRequest, campaign_id: int) -> HttpResponse:
        campaign = get_object_or_404(Campaign, pk=campaign_id)
        required_permissions = (
            "candidates.add_candidate",
            "candidates.change_candidate",
            "campaigns.add_campaignmember",
        )
        if not self.has_change_permission(request, campaign) or not request.user.has_perms(
            required_permissions
        ):
            raise PermissionDenied

        form = CandidateCSVUploadForm(request.POST or None, request.FILES or None)
        report = None
        if request.method == "POST" and form.is_valid():
            try:
                text = form.cleaned_data["csv_file"].read().decode("utf-8-sig")
                report = import_candidates_csv(
                    StringIO(text),
                    campaign=campaign,
                    default_phone_region=settings.DEFAULT_PHONE_REGION,
                    source="Admin CSV",
                )
            except (CSVImportError, UnicodeDecodeError) as exc:
                form.add_error("csv_file", str(exc))
            else:
                self.message_user(
                    request,
                    (
                        f"Processed {report.processed} rows: {report.imported} imported, "
                        f"{report.updated} updated, {report.duplicates} duplicates, "
                        f"{report.invalid} invalid, {report.skipped} skipped, "
                        f"{report.do_not_contact} do-not-contact."
                    ),
                    level=messages.SUCCESS,
                )

        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "campaign": campaign,
            "form": form,
            "report": report,
            "title": f"Import candidates into {campaign}",
        }
        return render(request, "admin/campaigns/campaign/import_candidates.html", context)

    @admin.action(description="Activate selected campaigns")
    def activate_campaigns(self, request, queryset):
        count = queryset.exclude(status=Campaign.Status.ACTIVE).update(status=Campaign.Status.ACTIVE)
        self.message_user(request, f"Activated {count} campaign(s).")

    @admin.action(description="Pause selected campaigns")
    def pause_campaigns(self, request, queryset):
        count = queryset.exclude(status=Campaign.Status.PAUSED).update(status=Campaign.Status.PAUSED)
        self.message_user(request, f"Paused {count} campaign(s).")


@admin.register(CampaignMember)
class CampaignMemberAdmin(admin.ModelAdmin):
    list_display = ("candidate", "campaign", "status", "messages_sent", "replies_received", "human_required", "updated_at")
    list_filter = ("campaign", "status", "human_required", "created_at")
    search_fields = ("candidate__first_name", "candidate__last_name", "candidate__phone", "candidate__email", "campaign__name")
    autocomplete_fields = ("campaign", "candidate")
    readonly_fields = ("created_at", "updated_at")
