from django.contrib import admin
from .models import  TreasuryIncome , TreasuryOutcome , Advance , Notification
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


class NotificationAdminSite(admin.ModelAdmin):
    list_display = ["creator" , "message"  ]
    list_filter = ["creator"]
    readonly_fields = ['uuid',"created_at","updated_at"]
    search_fields = ["craetor__username",'message', 'for_users']  
    fieldsets = FieldSets([
            'Advance Fields' ,
            'Other Fields'
        ],[
            [
                'creator',
                'message',
                'for_users',
                'seen_by_users',
                'deadline',
            ],[
                "uuid" ,
                "created_at",
                "updated_at"
            ]
    ]).fieldsets

admin.site.register(Advance , AdvanceAdminSite)
admin.site.register(TreasuryIncome , TreasuryRecordAdminSite)
admin.site.register(TreasuryOutcome , TreasuryRecordAdminSite)
admin.site.register(Notification , NotificationAdminSite)