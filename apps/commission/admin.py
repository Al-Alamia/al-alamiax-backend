from django.contrib import admin
from .models import (
    CoinChanger , 
    UserCommissionDetails , 
    BasicRecord,
    Commission , 
    Subscription ,
    Additional,
    )
from utils.admin_utils import FieldSets

# Register your models here.


class CoinChangerAdminSite(admin.ModelAdmin):
    list_display = ["egp_to_sar","date"]
    readonly_fields = ['uuid',"created_at","updated_at","date"]
    search_fields = ['uuid',"created_at","updated_at"]

    fieldsets = FieldSets([
            'CoinChanger Fields' ,
            'Other Fields'
        ],[
            [
                'egp_to_sar',
                'date',
            ],[
                "uuid" ,
                "created_at",
                "updated_at"
            ]
    ]).fieldsets


class UserCommissionDetailsAdminSite(admin.ModelAdmin):
    list_display = ["user","basic"]
    readonly_fields = ['uuid',"created_at","updated_at"]
    search_fields = ['user__username']   + ['uuid',"created_at","updated_at"]
    fieldsets = FieldSets([
            'UserCommissionDetails Fields' ,
            'Other Fields'
        ],[
            [
                'user',
                'basic',
            ],[
                "uuid" ,
                "created_at",
                "updated_at"
            ]
    ]).fieldsets

class BasicRecordAdminSite(admin.ModelAdmin):
    list_display = ["user","date","take_annual","basic"]
    list_filter = ["user","date"]
    readonly_fields = ['uuid',"created_at","updated_at"]
    search_fields = ['user__username',"date"]  + ['uuid',"created_at","updated_at"] 
    fieldsets = FieldSets([
            'Basic Fields' ,
            'Other Fields'
        ],[
            [
                'user',
                'deduction_days',
                'deduction_money',
                'kpi',
                'gift',
                'take_annual',
                'date',           
                'basic',
            ],[
                "uuid" ,
                "created_at",
                "updated_at"
            ]
    ]).fieldsets

class CommissionAdminSite(admin.ModelAdmin):
    list_display = ["user","date","basic","salary"]
    list_filter = ["date"]
    readonly_fields = ['uuid',"created_at","updated_at"]
    search_fields = ['basic',"date","salary","user"]  + ['uuid',"created_at","updated_at"]
    fieldsets = FieldSets([
            'Commission Fields' ,
            'Other Fields'
        ],[
            [
                "user",
                "basic",
                "target",
                "target_Team" ,
                "plus" ,
                "american" ,
                "american_count" ,
                "subscriptions" ,
                "subscriptions_count",
                "deduction" ,
                "gift" ,
                "salary" ,
                "date" ,
            ],[
                "uuid" ,
                "created_at",
                "updated_at",
            ]
    ]).fieldsets
    
    
class SubscriptionAdminSite(admin.ModelAdmin):
    list_display = ["count","value"]
    readonly_fields = ['uuid',"created_at","updated_at"]
    fieldsets = FieldSets([
            'Subscription Fields' ,
            'Other Fields'
        ],[
            [
                "count",
                "value",
            ],[
                "uuid" ,
                "created_at",
                "updated_at",
            ]
    ]).fieldsets
    
    
class AdditionalAdminSite(admin.ModelAdmin):
    list_display = ["plus","american_leads"]
    readonly_fields = ['uuid',"created_at","updated_at"]
    fieldsets = FieldSets([
            'Subscription Fields' ,
            'Other Fields'
        ],[
            [
                "plus",
                "american_leads",
            ],[
                "uuid" ,
                "created_at",
                "updated_at",
            ]
    ]).fieldsets


admin.site.register(CoinChanger, CoinChangerAdminSite)
admin.site.register(UserCommissionDetails , UserCommissionDetailsAdminSite)
admin.site.register(BasicRecord , BasicRecordAdminSite)
admin.site.register(Commission , CommissionAdminSite)
admin.site.register(Subscription , SubscriptionAdminSite)
admin.site.register(Additional , AdditionalAdminSite)