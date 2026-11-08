from django.contrib import admin

from .models import ReportField, ReportSection, ReportSubmission, ReportType, ReportValue


@admin.register(ReportType)
class ReportTypeAdmin(admin.ModelAdmin):
    list_display = ["name", "frequency", "is_active", "order"]
    list_filter = ["frequency", "is_active"]
    search_fields = ["name"]
    filter_horizontal = ["departments", "excluded_users"]


@admin.register(ReportSection)
class ReportSectionAdmin(admin.ModelAdmin):
    list_display = ["name", "report_type", "order", "is_active"]
    list_filter = ["report_type"]


@admin.register(ReportField)
class ReportFieldAdmin(admin.ModelAdmin):
    list_display = ["label", "section", "kind", "required", "order", "is_active"]
    list_filter = ["kind", "required"]


@admin.register(ReportSubmission)
class ReportSubmissionAdmin(admin.ModelAdmin):
    list_display = ["report_type", "user", "period_start", "period_end", "is_late"]
    list_filter = ["report_type", "is_late"]
    raw_id_fields = ["user"]


@admin.register(ReportValue)
class ReportValueAdmin(admin.ModelAdmin):
    list_display = ["submission", "field", "number", "text"]
    raw_id_fields = ["submission", "field"]
