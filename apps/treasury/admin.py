from django.contrib import admin

from .models import Advance, AdvanceInstallment, ImportBatch, ProjectGroup, TreasuryEntry


@admin.register(ProjectGroup)
class ProjectGroupAdmin(admin.ModelAdmin):
    list_display = ["name", "created_by"]


@admin.register(ImportBatch)
class ImportBatchAdmin(admin.ModelAdmin):
    list_display = ["uuid", "row_count", "created_by", "reversed_at"]


@admin.register(TreasuryEntry)
class TreasuryEntryAdmin(admin.ModelAdmin):
    list_display = ["date", "direction", "category", "amount", "details", "group"]


@admin.register(Advance)
class AdvanceAdmin(admin.ModelAdmin):
    list_display = ["user", "amount", "installments", "start_period", "status"]


@admin.register(AdvanceInstallment)
class AdvanceInstallmentAdmin(admin.ModelAdmin):
    list_display = ["advance", "period", "amount"]
