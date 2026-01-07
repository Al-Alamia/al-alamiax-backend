from django.contrib import admin
from import_export.admin import ImportExportModelAdmin
from import_export import resources, fields
from import_export.widgets import ForeignKeyWidget

from .models import (
    User , 
    Department ,
    Project ,
    ArrivingLeaving ,
    Lead ,
    Profile ,
    UpdateHistory , 
    Request , 
    FingerPrintID , 
    ZKConfig ,
    ReportRecord
)
from utils.admin_utils import FieldSets

class UserResource(resources.ModelResource):
    project_name = fields.Field(
        column_name='project',
        attribute='project',
        widget=ForeignKeyWidget(Project, 'name')
    )
    department_name = fields.Field(
        column_name='department',
        attribute='department',
        widget=ForeignKeyWidget(Department, 'name')
    )
    
    basic_salary = fields.Field(
        column_name='basic_salary',
        attribute='usercommissiondetails__basic'
    )
    set_deduction_rules = fields.Field(
        column_name='set_deduction_rules',
        attribute='usercommissiondetails__set_deduction_rules'
    )
    set_global_commission_rules = fields.Field(
        column_name='set_global_commission_rules',
        attribute='usercommissiondetails__set_global_commission_rules'
    )
    will_arrive_at = fields.Field(
        column_name='will_arrive_at',
        attribute='usercommissiondetails__will_arrive_at'
    )
    will_leave_at = fields.Field(
        column_name='will_leave_at',
        attribute='usercommissiondetails__will_leave_at'
    )

    class Meta:
        model = User
        fields = (
            'username', 'password_normal','profile__phone','annual_count', 'is_active', "first_name", "last_name", 'project_name', 'role', 'title', 'department_name', 'crm_username', 
            'basic_salary', 'set_deduction_rules', 'set_global_commission_rules', 'will_arrive_at', 'will_leave_at'
        )
        export_order = (
            'username', 'password_normal','profile__phone','annual_count', 'is_active', "first_name", "last_name", 'project_name', 'role', 'title', 'department_name', 'crm_username', 
            'basic_salary', 'set_deduction_rules', 'set_global_commission_rules', 'will_arrive_at', 'will_leave_at'
        )
        
    def export(self, *args, queryset=None, **kwargs):
        return super().export(*args, queryset=queryset.filter(is_superuser=False), **kwargs)

# Register your models here..
class UserAdminSite(ImportExportModelAdmin):
    resource_class = UserResource
    list_display = ("username","crm_username",'role',"department","project","annual_count","fp_id","is_active","is_staff","is_superuser")
    list_filter = ("project","department","role")
    readonly_fields = ['uuid',"created_at","updated_at"]
    search_fields = ['username' , 'uuid' , 'first_name',"fp_id"]  
    fieldsets = FieldSets([
            'Login Fields' ,
            'Company Fields',
            'Other Fields'
        ],[
            [
                'username',
                'password_normal',
                'groups',
                'is_active',
                'is_staff',
                'is_superuser',
                "first_name",
                "last_name",
            ] ,
            [
                "project",
                "role",
                "title",
                "department" ,
                "crm_username" ,
                "annual_count",
                "fp_id",
            ],
            [
                "uuid" ,
                "created_at",
                "updated_at"
            ]
    ]).fieldsets

class ProfileAdminSite(ImportExportModelAdmin):
    list_display = ["user","telegram_id"]
    list_filter = ["user"]
    readonly_fields = ['uuid',"created_at","updated_at"]
    search_fields = ['user__username' , 'uuid' , 'telegram_id']  
    fieldsets = FieldSets([
            'Profile Fields' ,
            'Other Fields'
        ],[
            [
                'user',
                'picture',
                'phone',
                'telegram_id',
                'about',
            ],[
                "uuid" ,
                "created_at",
                "updated_at"
            ]
    ]).fieldsets

class ArrivingLeavingResource(resources.ModelResource):
    class Meta:
        model = ArrivingLeaving  


class ArrinigLeavingAdminSite(ImportExportModelAdmin):
    resource_classes = [ArrivingLeavingResource]
    list_display = ["user","date","arriving_at","leaving_at",]
    list_filter = ["user","date"]
    readonly_fields = ['uuid',"created_at","updated_at","date" ,"arriving_at"]
    search_fields = ['user__username' , 'uuid' , 'date']  
    fieldsets = FieldSets([
            'Attendance Fields' ,
            'Other Fields'
        ],[
            [
                'user',
                'date',
                'arriving_at',
                'leaving_at',
            ],[
                "uuid" ,
                "created_at",
                "updated_at"
            ]
    ]).fieldsets


class LeadAdminSite(ImportExportModelAdmin):
    list_display = ["user","phone",'project',"date"]
    list_filter = ["user","date" ,'project']
    readonly_fields = ['uuid',"created_at","updated_at"]
    search_fields = ['phone' ,'name', 'uuid' , 'date__date']  
    fieldsets = FieldSets([
            'Lead Fields' ,
            'Other Fields'
        ],[
            [
                'user',
                'phone',
                'name',
                'date',
                'project',
            ],[
                "uuid" ,
                "created_at",
                "updated_at"
            ]
    ]).fieldsets


class ProjectAdminSite(ImportExportModelAdmin):
    list_display = ["name"]
    # list_filter = ["user","date" ,'project']
    readonly_fields = ['uuid',"created_at","updated_at"]
    # search_fields = ['name', 'uuid']  
    fieldsets = FieldSets([
            'Profile Fields' ,
            'Other Fields'
        ],[
            [
                'name',
                'logo',
            ],[
                "uuid" ,
                "created_at",
                "updated_at"
            ]
    ]).fieldsets


class DepartmentAdminSite(ImportExportModelAdmin):
    list_display = ["name"]
    # list_filter = ["user","date" ,'project']
    readonly_fields = ['uuid',"created_at","updated_at"]
    # search_fields = ['name', 'uuid']  
    fieldsets = FieldSets([
            'Profile Fields' ,
            'Other Fields'
        ],[
            [
                'name',
            ],[
                "uuid" ,
                "created_at",
                "updated_at"
            ]
    ]).fieldsets




class UpdateHistoryAdminSite(ImportExportModelAdmin):
    list_display = ["model_uuid","user" ,"model_name", "updated_at"]
    list_filter = ["user" ,  "model_name","updated_at"]
    readonly_fields = ["updated_at"]
    search_fields = ['model_name', 'model_uuid' , "user__username"]  
    fieldsets = FieldSets([
            'UpdateHistory Fields' ,
            'Other Fields'
        ],[
            [
                'model_uuid',
                'model_name',
                'user',
                'previous_values',
            ],[
                "updated_at"
            ]
    ]).fieldsets


class RequestAdminSite(ImportExportModelAdmin):
    list_display = ["user" ,"type","status", "department","date"]
    list_filter = ["user" ,  "department","status" , "type"]
    readonly_fields = ['uuid',"created_at","updated_at" , "department" ]
    search_fields = ['user__username','details', 'department__name' , "uuid"]  
    fieldsets = FieldSets([
            'UpdateHistory Fields' ,
            'Other Fields'
        ],[
            [
                'user',
                'type',
                'status',
                'details',
                'note',
                'date',
            ],[
                "uuid" ,
                "created_at",
                "updated_at" ,
                "department",
            ]
    ]).fieldsets


class FingerPrintIDAdminSite(ImportExportModelAdmin):
    list_display = ["user","name" ,"unique_id"]
    list_filter = ["user" ]
    readonly_fields = ['uuid',"created_at","updated_at" ]
    search_fields = ['user__username',"unique_id" ,"name"]  
    fieldsets = FieldSets([
            'FingerPrintID Fields' ,
            'Other Fields'
        ],[
            [
                'name', 
                'user',
                'unique_id',
            ],[
                "uuid" ,
                "created_at",
                "updated_at" ,
            ]
    ]).fieldsets
    
    
class ZKConfigAdminSite(ImportExportModelAdmin):
    list_display = ["ip","port" ,"timeout","password" , "is_default" , "last_uid"]
    list_filter = ["is_default"]
    readonly_fields = ['uuid',"created_at","updated_at" ]
    search_fields = ['ip',"port"]  
    fieldsets = FieldSets([
            'ZKConfig Fields' ,
            'Other Fields'
        ],[
            [
                'ip', 
                'port',
                'timeout',
                'password',
                'force_udp',
                'ommit_ping',
                'is_default',
                'last_uid',
            ],[
                "uuid" ,
                "created_at",
                "updated_at" ,
            ]
    ]).fieldsets
    
class ReportRecordAdminSite(ImportExportModelAdmin):
    list_display = ["user", "date"]
    list_filter = ["user","date"]
    readonly_fields = ['uuid',"created_at","updated_at" ]
    search_fields = ["user","date","json_data"]
    fieldsets = FieldSets([
            'ZKConfig Fields' ,
            'Other Fields'
        ],[
            [
                "user",
                "date",
                "json_data"            
                ],[
                "uuid" ,
                "created_at",
                "updated_at" ,
            ]
    ]).fieldsets

admin.site.site_title = "WFM-System"
admin.site.site_header = "WFM-System"
admin.site.register(User , UserAdminSite)
admin.site.register(Department, DepartmentAdminSite)
admin.site.register(Project , ProjectAdminSite)
admin.site.register(Profile,ProfileAdminSite)
admin.site.register(ArrivingLeaving,ArrinigLeavingAdminSite)
admin.site.register(Lead,LeadAdminSite)
admin.site.register(Request,RequestAdminSite)
admin.site.register(UpdateHistory , UpdateHistoryAdminSite)
admin.site.register(FingerPrintID , FingerPrintIDAdminSite)
admin.site.register(ZKConfig , ZKConfigAdminSite)
admin.site.register(ReportRecord , ReportRecordAdminSite)
