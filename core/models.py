from django.db import models
from django.db.models.signals import pre_save
import uuid
# Create your models here.


class BaseModel(models.Model):
    uuid = models.UUIDField(verbose_name='UUID' , max_length= 250 , default=uuid.uuid4 , primary_key=True , editable=False)
    created_at = models.DateTimeField(verbose_name="Creation Date & Time",auto_now_add=True )
    updated_at = models.DateTimeField(verbose_name="Update Date & Time",auto_now=True )

    class Meta:
        abstract = True




