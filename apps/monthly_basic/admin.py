from django.contrib import admin

from .models import MonthlyBasic


@admin.register(MonthlyBasic)
class MonthlyBasicAdmin(admin.ModelAdmin):
    list_display = ["user", "period", "status", "net"]
    list_filter = ["period", "status"]
    search_fields = ["user__username", "period"]
    readonly_fields = ["uuid", "created_at", "updated_at"]
