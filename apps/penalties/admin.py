from django.contrib import admin

from .models import Penalty, PenaltyType


@admin.register(PenaltyType)
class PenaltyTypeAdmin(admin.ModelAdmin):
    list_display = ["name", "kind", "default_value", "is_active"]
    list_filter = ["kind", "is_active"]
    search_fields = ["name"]


@admin.register(Penalty)
class PenaltyAdmin(admin.ModelAdmin):
    list_display = ["title", "user", "kind", "value", "date", "created_by", "voided_at"]
    list_filter = ["kind", "date"]
    search_fields = ["title", "user__username"]
    raw_id_fields = ["user", "created_by", "voided_by"]
