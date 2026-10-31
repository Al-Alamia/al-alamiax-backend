from django.contrib import admin

from .models import BasicSalary, DailyBonusStep, DepartmentRates, ExchangeRate


@admin.register(BasicSalary)
class BasicSalaryAdmin(admin.ModelAdmin):
    list_display = ["user", "amount", "effective_from"]
    raw_id_fields = ["user", "created_by"]


@admin.register(ExchangeRate)
class ExchangeRateAdmin(admin.ModelAdmin):
    list_display = ["month", "currency", "rate_to_egp"]


class DailyBonusStepInline(admin.TabularInline):
    model = DailyBonusStep
    extra = 0


@admin.register(DepartmentRates)
class DepartmentRatesAdmin(admin.ModelAdmin):
    list_display = ["department", "effective_from", "american_lead_price"]
    list_filter = ["department"]
    inlines = [DailyBonusStepInline]
