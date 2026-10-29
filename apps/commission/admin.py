from django.contrib import admin
from .models import (
    BasicRecord,
    Commission , 
    )
from utils.admin_utils import FieldSets

# Register your models here.


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
    
    
admin.site.register(BasicRecord , BasicRecordAdminSite)
admin.site.register(Commission , CommissionAdminSite)
