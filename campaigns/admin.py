from django.contrib import admin

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
    readonly_fields = ("created_at", "updated_at")
    inlines = (CampaignMemberInline,)


@admin.register(CampaignMember)
class CampaignMemberAdmin(admin.ModelAdmin):
    list_display = ("candidate", "campaign", "status", "messages_sent", "replies_received", "human_required", "updated_at")
    list_filter = ("campaign", "status", "human_required", "created_at")
    search_fields = ("candidate__first_name", "candidate__last_name", "candidate__phone", "candidate__email", "campaign__name")
    autocomplete_fields = ("campaign", "candidate")
    readonly_fields = ("created_at", "updated_at")

