from django.contrib import admin
from .models import (
    Commission , 
    )
from utils.admin_utils import FieldSets

# Register your models here.


class CommissionAdminSite(admin.ModelAdmin):
    list_display = ["user","date","salary"]
    list_filter = ["date"]
    readonly_fields = ['uuid',"created_at","updated_at"]
    search_fields = ["date","salary","user"]  + ['uuid',"created_at","updated_at"]
    fieldsets = FieldSets([
            'Commission Fields' ,
            'Other Fields'
        ],[
            [
                "user",
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
    
    
admin.site.register(Commission , CommissionAdminSite)
