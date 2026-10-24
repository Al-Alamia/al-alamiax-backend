from rest_framework.serializers import SerializerMethodField , DateField
from api_views.serializers import ModelSerializer ,  ForeignField , ManyToManyField  
import json
from datetime import datetime
from ..models import (
    Department,
    ReportRecord , 
    User , 
    Project , 
    Profile,
    Lead,
    Request ,
    UpdateHistory , 
    FingerPrintID
    )


class MultiDateFormatField(DateField):
    def to_internal_value(self, value):
        formats = ['%Y-%m-%d' , '%d-%m-%Y']
        for fmt in formats:
            try:
                return datetime.strptime(value, fmt).date()
            except ValueError:
                continue
        self.fail('invalid',format=' ,'.join(formats))
        

class DepartmentSerializer(ModelSerializer):

    class Meta:
        model = Department
        fields = [
            "uuid",
            "name",
        ]


class ProjectSerializer(ModelSerializer):

    class Meta:
        model = Project
        fields = [
            "uuid",
            "name",
            "logo" ,
        ]

class ProfileSerializer(ModelSerializer):
    picture = SerializerMethodField()

    def get_picture(self, obj:Profile):
        if obj.picture:
            return obj.picture.url[1:]
        return None
    class Meta:
        model = Profile
        fields = [
            "uuid",
            # "user",
            "phone",
            "picture",
            "telegram_id",
            "about",
        ]

class UserSerializer(ModelSerializer):
    project = ProjectSerializer(read_only=True)
    department = DepartmentSerializer(read_only=True)
    profile = ProfileSerializer(read_only=True)

    has_basic = SerializerMethodField()
    has_commission = SerializerMethodField()

    def get_has_basic(self,obj):
        return getattr(obj,"has_basic",None)
    
    def get_has_commission(self,obj):
        return getattr(obj,"has_commission",None)
            
    class Meta:
        model = User
        fields = [
            "uuid",
            "username",
            "role",
            "project",
            "department",
            "title" ,
            "first_name",
            "last_name",
            "is_superuser",
            "is_active",
            "has_basic",
            "has_commission",
            "password",
            "profile",
            "crm_username",
            "annual_count",
            "fp_id",
        ]
        extra_kwargs = {"password": {"write_only": True, "required": False}}
        foreign_models = {
            "department": ForeignField("department",Department,'uuid') ,
            "project": ForeignField("project",Project,'uuid') ,
        }
    
    
    def create(self, validated_data: dict, *args, **kwargs):
        validated_data.pop("is_superuser",None)
        validated_data.pop("is_staff",None)
        password = validated_data.pop("password", None)
        user = super().create(validated_data, *args, **kwargs)
        user.set_password(password)
        user.save()
        return user

    def update(self, instance, validated_data: dict):
        validated_data.pop("password", None)
        return super().update(instance, validated_data)




class LeadSerializer(ModelSerializer):
    user = SerializerMethodField()
    
    def get_user(self,obj):
        return getattr(obj.user,"username",None)
    
    class Meta:
        model = Lead
        fields = [
            "uuid",
            "user",
            "phone",
            "name",
            "date",
            "project",
        ]
        foreign_models = {
            "user": ForeignField("user",User,'uuid') ,
        }

class FingerPrintIDSerializer(ModelSerializer):
    user = UserSerializer(read_only=True)

    class Meta:
        model = FingerPrintID
        fields = [
            "uuid",
            "user",
            "name",
            "unique_id",
            "created_at",
            "updated_at",

        ]
        foreign_models = {
            "user": ForeignField("user",User,'uuid') ,
        }




class RequestSerializer(ModelSerializer):
    user = UserSerializer(read_only=True)
    date = MultiDateFormatField()
    class Meta:
        model = Request
        fields = [
            "uuid",
            "user",
            "details",
            "type",
            "note",
            "department",
            "status",
            "date",
            "created_at",
            "updated_at",

        ]
        foreign_models = {
            "department": ForeignField("department",Department,'uuid') ,
            "user": ForeignField("user",User,'uuid') ,
        }



class UpdateHistorySerializer(ModelSerializer):
    previous = SerializerMethodField()
    def get_previous(self,obj:UpdateHistory):
        return json.loads(obj.previous_values)

    class Meta:
        model = UpdateHistory
        fields = [
            "user",
            "updated_at",
            "previous",
            "model_name",
            "model_uuid",
        ]


class ReportRecordSerializer(ModelSerializer):
    data = SerializerMethodField()
    user = UserSerializer(read_only=True)
    def get_data(self,obj:ReportRecord)-> dict :
        return obj.as_json()

    class Meta:
        model = ReportRecord
        fields = [
            "user",
            "data",
            "updated_at",
            "created_at",
        ]


