from django.contrib import admin

from .models import CommissionPlan, PlanVersion, Team


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ["name", "department", "leader", "is_active"]
    list_filter = ["department", "is_active"]
    search_fields = ["name", "leader__username"]
    raw_id_fields = ["leader"]
    filter_horizontal = ["agents"]


class PlanVersionInline(admin.TabularInline):
    model = PlanVersion
    extra = 0
    raw_id_fields = ["created_by"]


@admin.register(CommissionPlan)
class CommissionPlanAdmin(admin.ModelAdmin):
    list_display = ["kind", "department", "user", "team", "is_active"]
    list_filter = ["kind", "is_active"]
    raw_id_fields = ["user", "team"]
    inlines = [PlanVersionInline]
