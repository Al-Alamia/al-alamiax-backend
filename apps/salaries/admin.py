from django.contrib import admin

from .models import Salary, SalaryOverride


class SalaryOverrideInline(admin.TabularInline):
    model = SalaryOverride
    extra = 0


@admin.register(Salary)
class SalaryAdmin(admin.ModelAdmin):
    list_display = ["user", "period", "status"]
    list_filter = ["period", "status"]
    search_fields = ["user__username", "period"]
    readonly_fields = ["uuid", "created_at", "updated_at"]
    inlines = [SalaryOverrideInline]
