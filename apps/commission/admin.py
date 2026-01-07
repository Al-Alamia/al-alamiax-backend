from django.contrib import admin
from .models import (
    Team , 
    CoinChanger , 
    DeductionRules , 
    TargetSlice , 
    UserCommissionDetails , 
    BasicRecord,
    Commission , 
    Subscription ,
    Additional,
    )
from utils.admin_utils import FieldSets

# Register your models here.

class DedactionRulesAdminSite(admin.ModelAdmin):
    list_display = ["late_time","deduction_days" , "department" , "is_global"]
    list_filter = ["department"]
    readonly_fields = ['uuid',"created_at","updated_at"]
    search_fields = ['name'] + ['uuid',"created_at","updated_at"] 
    fieldsets = FieldSets([
            'Deduction Fields' ,
            'Other Fields'
        ],[
            [
                'late_time',
                'deduction_days',
                'is_global',
                'department',
            ],[
                "uuid" ,
                "created_at",
                "updated_at"
            ]
    ]).fieldsets



class TargetSliceAdminSite(admin.ModelAdmin):
    list_display = ["name","min_value","max_value", "money" , "is_global" , 'is_money_percentage' , 'department']
    list_filter = ["is_global" , "department" , "is_money_percentage"]
    readonly_fields = ['uuid',"created_at","updated_at"]
    search_fields = ['min_value', 'max_value' , "money"] + ["name"] + ['uuid',"created_at","updated_at"]
    fieldsets = FieldSets([
            'TargetSlice Fields' ,
            'Other Fields'
        ],[
            [
                "name",
                'min_value',
                'max_value',
                'money',
                'is_global',
                'is_money_percentage',
                'department',
            ],[
                "uuid" ,
                "created_at",
                "updated_at"
            ]
    ]).fieldsets
 
class TeamAdminSite(admin.ModelAdmin):
    list_display = ["name","leader"]
    # list_filter = ["is_global" ]
    readonly_fields = ['uuid',"created_at","updated_at"]
    search_fields = ['name', 'leader__username' , "agents__username"]   + ['uuid',"created_at","updated_at"]
    fieldsets = FieldSets([
            'Team Fields' ,
            'Other Fields'
        ],[
            [
                'name',
                'leader',
                'agents',
                'commission_rules',
            ],[
                "uuid" ,
                "created_at",
                "updated_at"
            ]
    ]).fieldsets


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
    list_display = ["user","basic","set_deduction_rules","set_global_commission_rules" ,"will_arrive_at", "will_leave_at"]
    list_filter = ["set_deduction_rules" , "set_global_commission_rules" ]
    readonly_fields = ['uuid',"created_at","updated_at"]
    search_fields = ['user__username']   + ['uuid',"created_at","updated_at"]
    fieldsets = FieldSets([
            'UserCommissionDetails Fields' ,
            'Other Fields'
        ],[
            [
                'user',
                'basic',
                'set_deduction_rules',
                'set_global_commission_rules',
                'deduction_rules',
                'commission_rules',
                'will_arrive_at',
                'will_leave_at',

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


admin.site.register(Team , TeamAdminSite)
admin.site.register(CoinChanger, CoinChangerAdminSite)
admin.site.register(DeductionRules,DedactionRulesAdminSite)
admin.site.register(TargetSlice , TargetSliceAdminSite)
admin.site.register(UserCommissionDetails , UserCommissionDetailsAdminSite)
admin.site.register(BasicRecord , BasicRecordAdminSite)
admin.site.register(Commission , CommissionAdminSite)
admin.site.register(Subscription , SubscriptionAdminSite)
admin.site.register(Additional , AdditionalAdminSite)