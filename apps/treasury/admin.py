from django.contrib import admin
from .models import  TreasuryIncome , TreasuryOutcome , Advance
from utils.admin_utils import FieldSets
# Register your models here.



class TreasuryRecordAdminSite(admin.ModelAdmin):
    list_display = ["creator" , "amount" , "details" ]
    list_filter = ["creator" ]
    readonly_fields = ['uuid',"created_at","updated_at"]
    search_fields = ['creator__username', 'amount' , "details" ,"treasury__name" ]  
    fieldsets = FieldSets([
            'Treasury Record Fields' ,
            'Other Fields'
        ],[
            [
                'creator',
                'amount',
                'details',
            ],[
                "uuid" ,
                "created_at",
                "updated_at"
            ]
    ]).fieldsets


class AdvanceAdminSite(admin.ModelAdmin):
    list_display = ["creator" , "user" , "amount" ]
    list_filter = ["creator","user"]
    readonly_fields = ['uuid',"created_at","updated_at"]
    search_fields = ['creator__username', 'amount' , "user__username"]  
    fieldsets = FieldSets([
            'Advance Fields' ,
            'Other Fields'
        ],[
            [
                'creator',
                'user',
                'amount',
            ],[
                "uuid" ,
                "created_at",
                "updated_at"
            ]
    ]).fieldsets


admin.site.register(Advance , AdvanceAdminSite)
admin.site.register(TreasuryIncome , TreasuryRecordAdminSite)
admin.site.register(TreasuryOutcome , TreasuryRecordAdminSite)
