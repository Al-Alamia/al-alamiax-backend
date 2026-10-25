from django.contrib import admin

from .models import Notification, NotificationRecipient


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ["kind", "title", "sender", "created_at"]
    list_filter = ["kind"]
    readonly_fields = ["uuid", "created_at", "updated_at"]
    search_fields = ["title", "message"]


admin.site.register(NotificationRecipient)
