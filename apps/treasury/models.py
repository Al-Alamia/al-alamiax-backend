from django.db import models
from django.db.models.signals import pre_save , post_save
from apps.users.types import RequestStatuses
from core.models import  BaseModel 
from apps.users.models import User , create_update_history
from django.utils.timezone import now , timedelta
# from commission.models import BasicRecord

def tomorrow():
    return now() + timedelta(days=1)

class TreasuryIncome(BaseModel):
    creator = models.ForeignKey(User,verbose_name="Creator" , on_delete=models.SET_NULL , null=True ,  limit_choices_to={'role': 'OWNER'} )#limit_choices_to={'role': 'OWNER'}
    amount = models.PositiveIntegerField(verbose_name="Amount")
    details = models.CharField(verbose_name="Details" , max_length=250 )


class Advance(BaseModel):
    creator = models.ForeignKey(User,verbose_name="Creator" ,  on_delete=models.SET_NULL , null=True , related_name="advance_creator" , limit_choices_to={'role': 'OWNER'})#limit_choices_to={'role': 'OWNER'}
    user = models.ForeignKey(User,verbose_name="Taker" ,  on_delete=models.SET_NULL , null=True , related_name="advance_taker" ,limit_choices_to={'role__in': ['AGENT','MANAGER','HR']})#limit_choices_to={'role': 'OWNER'}
    amount = models.PositiveIntegerField(verbose_name="Amount")
    # status = models.CharField(verbose_name="Advance Status", max_length=50, choices=RequestStatuses.choices ,default=RequestStatuses.PENDING)
    status = models.CharField(verbose_name="Advance Status", max_length=50, choices=RequestStatuses.choices ,default=RequestStatuses.PENDING)



class TreasuryOutcome(BaseModel):
    creator = models.ForeignKey(User,verbose_name="Creator" ,  on_delete=models.SET_NULL , null=True , limit_choices_to={'role': 'OWNER'})#limit_choices_to={'role': 'OWNER'}
    amount = models.PositiveIntegerField(verbose_name="Amount")
    from_advance =  models.ForeignKey(Advance,verbose_name="Advance" ,  on_delete=models.CASCADE , null=True , blank=True)
    from_salary =  models.ForeignKey("commission.Commission",verbose_name="Salary" ,  on_delete=models.CASCADE , null=True , blank=True)
    from_basic =  models.ForeignKey("commission.BasicRecord",verbose_name="Basic" ,  on_delete=models.CASCADE , null=True , blank=True)
    details = models.CharField(verbose_name="Details" , max_length=250 )


class Notification(BaseModel):
    creator = models.ForeignKey(User,verbose_name="Creator" ,  on_delete=models.SET_NULL , null=True , limit_choices_to={'role': 'OWNER'})#limit_choices_to={'role': 'OWNER'}
    message = models.CharField(verbose_name="Message" , max_length=250 )
    for_users = models.ManyToManyField(User , related_name="for_users",verbose_name="For Users")
    seen_by_users = models.ManyToManyField(User ,blank=True, related_name="seen_by_users",verbose_name="Seen by Users")
    deadline = models.DateTimeField(verbose_name="Deadline",default=tomorrow)






def add_treasury_record(sender:User, instance:Advance, created:bool, **kwargs):
    if instance.status == RequestStatuses.ACCEPTED:
        try :
            new_record = TreasuryOutcome.objects.get(from_advance=instance)
            new_record.amount = instance.amount
            new_record.creator = instance.creator
            new_record.details = f"Advance to {instance.user} amount {instance.amount} EGP" 
            new_record.save()
        except TreasuryOutcome.DoesNotExist :
            new_record = TreasuryOutcome.objects.create(
                creator = instance.creator,
                amount = instance.amount ,
                from_advance=instance,
                details = f"Advance to {instance.user} amount {instance.amount} EGP" , 
            )
            new_record.save()
        except Exception as e :
            print(e)

pre_save.connect(create_update_history, sender=TreasuryIncome)
pre_save.connect(create_update_history, sender=TreasuryOutcome)
pre_save.connect(create_update_history, sender=Advance)
post_save.connect(add_treasury_record, sender=Advance)


