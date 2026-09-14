from django.contrib import admin

from .models import AuditEvent


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ("event_type", "entity_type", "entity_id", "actor", "created_at")
    list_filter = ("event_type", "entity_type", "created_at")
    search_fields = ("description", "entity_type", "entity_id")
    readonly_fields = ("event_type", "description", "entity_type", "entity_id", "metadata", "actor", "created_at")
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

