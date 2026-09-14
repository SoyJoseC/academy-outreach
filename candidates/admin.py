from django.contrib import admin

from .models import Candidate


@admin.register(Candidate)
class CandidateAdmin(admin.ModelAdmin):
    list_display = ("full_name", "phone", "email", "country", "status", "do_not_contact", "updated_at")
    list_filter = ("status", "do_not_contact", "country", "created_at")
    search_fields = ("first_name", "last_name", "phone", "email", "activecampaign_id")
    readonly_fields = ("created_at", "updated_at")
    date_hierarchy = "created_at"

    @admin.display(description="Candidate", ordering="last_name")
    def full_name(self, obj: Candidate) -> str:
        return str(obj)

