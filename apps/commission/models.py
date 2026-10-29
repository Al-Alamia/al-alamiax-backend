from django.db import models 
from django.core.exceptions import ValidationError
from django.db.models.signals import pre_save , post_save , post_delete
from apps.users.models import  User ,Department , create_update_history
from core.models import BaseModel
import typing , datetime
from django.utils.timezone import now
from apps.treasury.models import TreasuryOutcome
# Create your models here.


class UserCommissionDetails(BaseModel):
    user = models.OneToOneField(User,verbose_name="User" , on_delete=models.CASCADE)
    basic = models.PositiveIntegerField(verbose_name="Basic Salary"  , default= 0)

    def __str__(self):
        return f"{self.user} - {self.basic}"

    class Meta:
        verbose_name = 'User Commission Details'
        verbose_name_plural = 'User Commission Details'



class CoinChanger(BaseModel):
    egp_to_sar = models.FloatField(verbose_name="1 SAR equal to ? in EGP")
    date  = models.DateField(verbose_name="Changer Date" , default=now )
    
    def __str__(self):
        return self.date.strftime("%Y/%m")

    class Meta:
        verbose_name = 'Coin Changer'
        verbose_name_plural = 'Coin Changers'    
        unique_together = ['date',]

    def calc_concurrency(self , sar_value:typing.Union[int,float]):
        return sar_value * self.egp_to_sar
        

class BasicRecord(BaseModel):
    user = models.ForeignKey(User, verbose_name="User", on_delete=models.SET_NULL , null=True)
    take_annual = models.IntegerField(verbose_name="Take Annual" , default= 0 )
    # user_commission_details = models.ForeignKey(UserCommissionDetails, verbose_name="User Commission Details", on_delete=models.SET_NULL , null=True)
    deduction_days = models.FloatField(verbose_name="Deduction Days" , default=0)
    deduction_money = models.IntegerField(verbose_name="Deduction Money" , default=0)
    kpi = models.FloatField(verbose_name="KPI" , default=0)
    gift = models.FloatField(verbose_name="Gift" , default=0)
    basic = models.FloatField(verbose_name="Taken Basic" , default=0)
    date  = models.DateField(verbose_name="Date" , default=now )
    
    def __str__(self):
        return self.date.strftime("%Y/%m")

    class Meta:
        unique_together = ["date","user"]


class Commission(BaseModel):
    user = models.ForeignKey(User, verbose_name="User", on_delete=models.SET_NULL , null=True)
    basic = models.ForeignKey(BasicRecord,verbose_name="Basic" , on_delete=models.SET_NULL , null=True)
    target = models.FloatField(verbose_name="Target" , default=0 )
    target_Team = models.FloatField(verbose_name="Target Team" , default=0)
    plus = models.FloatField(verbose_name="Plus +2" , default=0)
    american = models.FloatField(verbose_name="American Leads" , default=0)
    american_count = models.IntegerField(verbose_name="American Leads Count" , default=0)
    subscriptions = models.FloatField(verbose_name="Subscriptions" , default=0)
    subscriptions_count = models.IntegerField(verbose_name="Subscriptions Count" , default=0)
    deduction = models.FloatField(verbose_name="Deduction" , default=0)
    gift = models.FloatField(verbose_name="Gift" , default=0)
    salary = models.FloatField(verbose_name="Total of Salary" , default=0)
    date  = models.DateField(verbose_name="Date" , default=datetime.date.today )

    def __str__(self):
        return self.date.strftime("%Y/%m")

    class Meta:
        unique_together = ["date","user"]
        
        

class Subscription(BaseModel):
    count = models.IntegerField(verbose_name="Subscriptions Count",unique=True)
    value = models.IntegerField(verbose_name="Money" )


class Additional(BaseModel):
    plus = models.IntegerField(verbose_name="Plus +2 Price")
    american_leads = models.IntegerField(verbose_name="American Leads Price" )


def create_user_commission_details(sender, instance:User, created ,**kwargs):
    if created :
        details = UserCommissionDetails.objects.create(
            user=instance ,
            basic=kwargs.get('basic',0),
            )
        details.save()


def create_Outcome_record(sender, instance:BasicRecord, created ,**kwargs):
    if created :
        details = TreasuryOutcome.objects.create(
            amount = instance.basic ,
            from_basic =  instance ,
            details = f"Basic Record {instance.user} Amount {int(instance.basic)}"
        )
        details.save()
    else :
        details = TreasuryOutcome.objects.get(
            from_basic =  instance ,
        )
        details.amount = instance.basic
        details.details = f"Basic Record {instance.user} Amount {int(instance.basic)}"
        details.save()
        

def create_Outcome_record_salary(sender, instance:Commission, created ,**kwargs):
    if created :
        details = TreasuryOutcome.objects.create(
            amount = instance.salary ,
            from_salary =  instance ,
            details = f"Salary {instance.user} Amount {int(instance.salary)}"
        )
        details.save()
    else :
        details = TreasuryOutcome.objects.get(
            from_salary =  instance ,
        )
        details.amount = instance.salary
        details.details = f"Salery {instance.user} Amount {int(instance.salary)}"
        details.save()


pre_save.connect(create_update_history,sender=CoinChanger)
pre_save.connect(create_update_history, sender=UserCommissionDetails)
pre_save.connect(create_update_history, sender=CoinChanger)
pre_save.connect(create_update_history, sender=BasicRecord)
pre_save.connect(create_update_history, sender=Commission)
post_save.connect(create_user_commission_details,sender=User)
# post_save.connect(create_Outcome_record,sender=BasicRecord)
post_save.connect(create_Outcome_record_salary,sender=Commission)