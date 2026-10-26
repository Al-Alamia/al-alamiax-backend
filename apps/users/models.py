from django.db import models
from django.db.models import Q
from django.contrib.auth.models import AbstractUser 
from .managers import (
        CustomUserManager ,
        AgentObjects ,
        ManagerObjects ,
        OwnerObjects
    )
from .types import UserTypes , DepartmentCodes , StockMarkets , LeadStatuses , CallStatuses , AssignmentKinds , LeadUpdateTypes , DeviceStatus , FileCategory
from .storage import private_storage
from utils.models_utils import image_upload_path , validate_lead_number , validate_role , validate_user_number
from django.db.models.signals import pre_save , post_save , post_delete
from core.models import BaseModel
import json
import os
import logging
from django.utils.timezone import now
from django.urls import reverse
from uuid import uuid1, uuid4
from zk import ZK, const
from zk.attendance import Attendance
from zk.user import User as ZkUser
from zk.finger import Finger


logger = logging.getLogger(__name__)


class Project(BaseModel):
    name = models.CharField(verbose_name="Project Name", max_length=100)
    logo = models.ImageField(verbose_name="Logo", upload_to='projects-logo/')
    def __str__(self):
        return self.name


class Department(BaseModel):
    name = models.CharField(verbose_name="Department Name", max_length=100)
    code = models.CharField(verbose_name="Code", max_length=20, choices=DepartmentCodes.choices, default=DepartmentCodes.OTHER)
    def __str__(self):
        return self.name


class User(AbstractUser , BaseModel):
    ## managers with customization
    objects = CustomUserManager()
    owners = OwnerObjects()
    managers = ManagerObjects()
    agents = AgentObjects()

    ### other normal fields

    project = models.ForeignKey(Project,verbose_name="Project" , on_delete=models.SET_NULL , null=True)
    role = models.CharField(max_length=100 , verbose_name="Role" , choices=UserTypes.choices , default=UserTypes.AGENT, validators=[validate_role])
    title = models.CharField(max_length=100 , verbose_name="Title" , default='Agent')
    department = models.ForeignKey( Department,verbose_name="Department", on_delete=models.SET_NULL, null=True)
    crm_username = models.CharField(max_length=200 , verbose_name="CRM Username" , blank=True  )
    fp_id = models.CharField(verbose_name="Figner Print ID",max_length=200 , unique=False,blank=True)
    must_change_password = models.BooleanField(verbose_name="Must Change Password", default=False)
    
    def __str__(self):
        return f"{self.username}"
    
    class Meta:
        verbose_name = "User"
        constraints = [
            models.UniqueConstraint(fields=["fp_id"], condition=~Q(fp_id=""), name="unique_non_blank_fp_id"),
        ]


class FingerPrintID(BaseModel):
    name = models.CharField(max_length=100 , verbose_name="Name" , default='PC')
    user = models.ForeignKey(User,verbose_name="User" , on_delete=models.CASCADE )
    unique_id = models.CharField(verbose_name="Unique ID", max_length=100)
    status = models.CharField(verbose_name="Status", max_length=20, choices=DeviceStatus.choices, default=DeviceStatus.PENDING)
    decided_by = models.ForeignKey(User, verbose_name="Decided By", on_delete=models.SET_NULL, null=True, blank=True, related_name="devices_decided")
    decided_at = models.DateTimeField(verbose_name="Decided At", null=True, blank=True)
    last_used_at = models.DateTimeField(verbose_name="Last Used At", null=True, blank=True)
    user_agent = models.CharField(verbose_name="User Agent", max_length=255, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "unique_id"], name="uniq_device_per_user"),
        ]

    def __str__(self):
        return f"{self.name} - {self.user}"


def user_file_upload_path(instance, filename):
    ext = os.path.splitext(filename)[1].lower()
    return f"user_files/{instance.user_id}/{uuid4().hex}{ext}"


class UserFile(BaseModel):
    user = models.ForeignKey(User, verbose_name="User", on_delete=models.CASCADE, related_name="files")
    title = models.CharField(verbose_name="Title", max_length=150)
    category = models.CharField(verbose_name="Category", max_length=20, choices=FileCategory.choices)
    file = models.FileField(verbose_name="File", storage=private_storage, upload_to=user_file_upload_path)
    size = models.PositiveIntegerField(verbose_name="Size")
    content_type = models.CharField(verbose_name="Content Type", max_length=100)
    uploaded_by = models.ForeignKey(User, verbose_name="Uploaded By", on_delete=models.SET_NULL, null=True, related_name="files_uploaded")

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.title} - {self.user}"
        

class Profile(BaseModel):
    user = models.OneToOneField(User,verbose_name="User" , on_delete=models.CASCADE )
    phone = models.CharField(max_length=11 ,null=True,verbose_name="Phone Number" , validators=[validate_user_number])
    picture = models.ImageField(verbose_name="Profile Picture"  ,upload_to=image_upload_path  ,blank=True, null=True)
    telegram_id = models.PositiveIntegerField(verbose_name="Telegram ID" ,blank=True, null=True)
    about = models.TextField(verbose_name="About Text" , blank=True)
    
    class Meta: ...



class Lead(BaseModel):
    user = models.ForeignKey(User,verbose_name="User" , on_delete=models.SET_NULL , null=True )
    phone = models.CharField(max_length=20 ,verbose_name="Phone Number" ) # validators=[validate_lead_number]
    name = models.CharField(verbose_name="Lead Name", max_length=100)
    date = models.DateTimeField(verbose_name="Day Date", null=True,default=now )
    project = models.ForeignKey(Project,verbose_name="Project" , on_delete=models.SET_NULL , null=True)
    email = models.EmailField(verbose_name="Email", blank=True)
    description = models.TextField(verbose_name="Description", blank=True)
    stock_market = models.CharField(verbose_name="Stock Market", max_length=20, choices=StockMarkets.choices, blank=True)
    status = models.CharField(verbose_name="Status", max_length=20, choices=LeadStatuses.choices, default=LeadStatuses.NEW)
    call_status = models.CharField(verbose_name="Call Status", max_length=20, choices=CallStatuses.choices, default=CallStatuses.PENDING)
    is_hidden = models.BooleanField(verbose_name="Is Hidden", default=False)
    return_count = models.PositiveIntegerField(verbose_name="Return Count", default=0)
    class Meta:
        unique_together = ['user','phone']


class LeadScreenshot(BaseModel):
    lead = models.ForeignKey(Lead, verbose_name="Lead", on_delete=models.CASCADE, related_name="screenshots")
    image = models.ImageField(verbose_name="Image", upload_to="lead-screenshots/")


class LeadAssignment(BaseModel):
    lead = models.ForeignKey(Lead, verbose_name="Lead", on_delete=models.CASCADE, related_name="assignments")
    agent = models.ForeignKey(User, verbose_name="Agent", on_delete=models.CASCADE, related_name="lead_assignments")
    kind = models.CharField(verbose_name="Kind", max_length=10, choices=AssignmentKinds.choices)
    assigned_by = models.ForeignKey(User, verbose_name="Assigned By", on_delete=models.SET_NULL, null=True, related_name="lead_assignments_made")
    is_active = models.BooleanField(verbose_name="Is Active", default=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["lead", "kind"], condition=Q(is_active=True), name="one_active_assignment_per_kind"),
        ]


class LeadReturn(BaseModel):
    lead = models.ForeignKey(Lead, verbose_name="Lead", on_delete=models.CASCADE, related_name="returns")
    assignment = models.ForeignKey(LeadAssignment, verbose_name="Assignment", on_delete=models.CASCADE, related_name="returns")
    returned_by = models.ForeignKey(User, verbose_name="Returned By", on_delete=models.SET_NULL, null=True, related_name="lead_returns")
    reason = models.TextField(verbose_name="Reason")


class LeadUpdate(BaseModel):
    lead = models.ForeignKey(Lead, verbose_name="Lead", on_delete=models.CASCADE, related_name="updates")
    by = models.ForeignKey(User, verbose_name="By", on_delete=models.SET_NULL, null=True, related_name="lead_updates")
    type = models.CharField(verbose_name="Type", max_length=20, choices=LeadUpdateTypes.choices)
    from_value = models.CharField(verbose_name="From Value", max_length=255, blank=True)
    to_value = models.CharField(verbose_name="To Value", max_length=255, blank=True)
    note = models.TextField(verbose_name="Note", blank=True)

    class Meta:
        ordering = ["-created_at"]


class UpdateHistory(models.Model):
    user = models.ForeignKey(User, verbose_name="User", on_delete=models.SET_NULL, null=True)
    updated_at = models.DateTimeField( verbose_name="Updated At", auto_now_add=True)
    previous_values = models.TextField()  # Use TextField instead of JSONField
    model_name = models.CharField( max_length = 100 )  # Store the name of the model
    model_uuid = models.UUIDField()  # Store the UUID of the model instance

    class Meta:
        verbose_name = "Update History"
        verbose_name_plural = "Update Histories"
        indexes = [
            models.Index(fields=["model_name", "model_uuid"], name="updhist_model_idx"),
            models.Index(fields=["user"], name="updhist_user_idx"),
        ]

    def __str__(self):
        return f"{self.model_name} - {self.model_uuid} - {self.updated_at.date()}"



class ZKConfig(BaseModel):
    ip = models.CharField(verbose_name="IP Address",max_length=20,unique=True )
    port=models.PositiveBigIntegerField(verbose_name="Port")
    timeout = models.PositiveIntegerField(verbose_name="Connection Timeout")
    password = models.CharField(verbose_name="Password",max_length=100)
    force_udp = models.BooleanField(verbose_name= "Force UDP")
    ommit_ping = models.BooleanField(verbose_name= "Ommit Ping")
    is_default= models.BooleanField(verbose_name= "Set Default")
    last_uid = models.PositiveBigIntegerField(verbose_name="Last Machine UID")
    name = models.CharField(verbose_name="Name", max_length=100, blank=True)
    last_synced_at = models.DateTimeField(verbose_name="Last Synced At", null=True, blank=True)
    
    
    
class ReportRecord(BaseModel):
    user = models.ForeignKey(User,verbose_name="User",on_delete=models.CASCADE)
    date = models.DateField(verbose_name="Date of Record", null=True )
    json_data = models.TextField(verbose_name="Data as Serialized Json",max_length=2000)
    
    def set_data(self,data:dict):
        self.json_data = json.dumps(data)
        
    def as_json(self) -> dict:
        return json.loads(self.json_data)
        
    class Meta:
        unique_together = ['user','date']
    
    
def profile_creator_signal(sender:User, instance:User, created:bool, **kwargs):
    if created:
        profile , is_created = Profile.objects.get_or_create(user=instance)
        if is_created:
            profile.save()
    

def snapshot_values(instance) -> dict:
    """Field name -> str(value) for every concrete field; the format stored in UpdateHistory."""
    return {field.name: str(getattr(instance, field.name)) for field in instance._meta.fields}


def create_update_history(sender, instance:BaseModel, **kwargs):
    if issubclass(sender, BaseModel):  # Check if the sender is a subclass of BaseModel
        try : 
            old_instance = sender.objects.get(uuid=instance.uuid)
        except sender.DoesNotExist:
            return
        previous_values_str = json.dumps(snapshot_values(old_instance))
        UpdateHistory.objects.create(
            user=getattr(instance,"__by",None),  
            previous_values=previous_values_str,
            model_name=sender.__name__,  # Get the name of the model
            model_uuid=instance.uuid
        )


def fp_signal(sender:User , instance:User,created:bool,**kwargs):
    if created :
        zkconfig = ZKConfig.objects.filter(is_default=True).first()
        if zkconfig :
            zk = ZK(zkconfig.ip, port=zkconfig.port, timeout=zkconfig.timeout, password=zkconfig.password, force_udp=zkconfig.force_udp, ommit_ping=zkconfig.ommit_ping)
        else :
            zk = ZK("192.168.11.157", port=4370, timeout=5, password=0, force_udp=False, ommit_ping=False)
        conn = None
        try : 
            conn = zk.connect()
            conn.disable_device()
            if zkconfig and zkconfig.last_uid :
                next_id = zkconfig.last_uid 
            else :
                users = conn.get_users()
                next_id = max(map(lambda usr:usr.uid,users))
                
            next_uid = int(next_id + 1)
            conn.set_user(uid=next_uid,name=instance.username)
            if zkconfig :
                zkconfig.last_uid = next_uid
                zkconfig.save()
            # update() avoids re-entering this post_save signal
            User.objects.filter(pk=instance.pk).update(fp_id=str(next_uid))
            instance.fp_id = str(next_uid)
            conn.enable_device()
        except Exception as e:
            # a device (or fp_id) problem must never break user creation
            logger.exception("fp_signal failed for user %s: %s", instance.pk, e)
        finally:
            if conn:
                try:
                    conn.disconnect()
                except Exception as e:
                    logger.warning("fp_signal disconnect failed: %s", e)

def fp_delete(sender:BaseModel, instance:User, **kwargs):
    zkconfig = ZKConfig.objects.filter(is_default=True).first()
    if zkconfig :
        zk = ZK(zkconfig.ip, port=zkconfig.port, timeout=zkconfig.timeout, password=zkconfig.password, force_udp=zkconfig.force_udp, ommit_ping=zkconfig.ommit_ping)
    else :
        zk = ZK("192.168.11.157", port=4370, timeout=5, password=0, force_udp=False, ommit_ping=False)
    conn = None
    try : 
        conn = zk.connect()
        conn.disable_device()
        conn.delete_user(uid=int(instance.fp_id))
        conn.enable_device()
    except Exception as e:
        print(e)
    finally:
        if conn:
            conn.disconnect()

    

post_save.connect(profile_creator_signal, sender=User)
pre_save.connect(create_update_history, sender=Project)
pre_save.connect(create_update_history, sender=Department)
pre_save.connect(create_update_history, sender=FingerPrintID)
pre_save.connect(create_update_history, sender=User)
pre_save.connect(create_update_history, sender=Profile)
pre_save.connect(create_update_history, sender=Lead)
post_save.connect(fp_signal, sender=User)
post_delete.connect(fp_delete,sender=User)



