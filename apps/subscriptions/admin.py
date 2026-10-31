from django.contrib import admin

from .models import Payment, Subscription


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ["lead", "kind", "plan_name", "currency", "total_amount", "start_date", "end_date", "seller"]
    list_filter = ["kind", "currency", "market"]
    search_fields = ["plan_name", "lead__name", "lead__phone"]
    readonly_fields = ["uuid", "created_at", "updated_at"]


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ["subscription", "amount", "paid_on", "method", "recorded_by"]
    list_filter = ["method"]
    search_fields = ["transaction_id"]
    readonly_fields = ["uuid", "created_at", "updated_at"]
