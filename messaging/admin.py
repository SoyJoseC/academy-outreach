from django.contrib import admin

from .models import Message, SystemState


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("id", "candidate", "campaign", "direction", "status", "scheduled_at", "sent_at", "created_at")
    list_filter = ("campaign", "direction", "status", "created_at", "sent_at")
    search_fields = ("candidate__first_name", "candidate__last_name", "candidate__phone", "content", "provider_message_id")
    autocomplete_fields = ("candidate", "campaign", "campaign_member")
    readonly_fields = ("created_at", "updated_at", "generated_at", "sent_at", "delivered_at", "failed_at")
    date_hierarchy = "created_at"


@admin.register(SystemState)
class SystemStateAdmin(admin.ModelAdmin):
    list_display = ("outbound_enabled", "inbound_auto_reply_enabled", "paused_reason", "updated_at", "updated_by")
    readonly_fields = ("updated_at",)

    def has_add_permission(self, request):
        return not SystemState.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

