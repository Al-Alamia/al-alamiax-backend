from django.db import models 
from django.core.exceptions import ValidationError
from django.db.models.signals import pre_save , post_save , post_delete
from users.custom_types import RequestStatuses
from users.models import  User ,Department , create_update_history , Request , Project
from core.models import BaseModel
import typing , datetime
from django.utils.timezone import now
from treasury.models import TreasuryOutcome
from treasury.signals import notify
# Create your models here.


class TargetSlice(BaseModel):
    name = models.CharField(verbose_name="Name", max_length=150)
    min_value = models.PositiveIntegerField(verbose_name="Min Value")
    max_value = models.PositiveIntegerField(verbose_name="Max Value" )
    money = models.CharField(verbose_name="Commission", max_length=100)
    is_money_percentage = models.BooleanField(verbose_name="Set Commession as Percentage")
    is_global = models.BooleanField(verbose_name="Set Global Rule")
    department = models.ForeignKey(Department, verbose_name="Department", on_delete=models.CASCADE)
    
    class Meta:
        verbose_name = "Target Slice"
        verbose_name_plural = "Target Slices"
 
    def save(self, *args , **kwargs) -> None:
        if self.min_value >= self.max_value :
            raise ValidationError("Max Value must be greater than Min Value")
        return super().save(*args , **kwargs)

    def is_achieved(self,count:int):
        return count > self.min_value
        
    def is_in_range(self,count:int):
        return self.min_value < count < self.max_value

    def __str__(self):
        return f"{self.min_value} - {self.max_value} : {self.money} {'%' if self.is_money_percentage else 'EGP'}"



class DeductionRules(BaseModel):
    late_time = models.PositiveIntegerField(verbose_name="Late in Secounds")
    deduction_days = models.FloatField(verbose_name="Deduction in Days")
    is_global = models.BooleanField(verbose_name="Set Global Rule")
    department = models.ForeignKey(Department, verbose_name="Department", on_delete=models.CASCADE)
    class Meta:
        verbose_name = "Deduction Rules"
        verbose_name_plural = "Deduction Rules"

    def __str__(self) -> str:
        return f"{self.late_time/60}min - {self.deduction_days} day - {self.department}"



class UserCommissionDetails(BaseModel):
    user = models.OneToOneField(User,verbose_name="User" , on_delete=models.CASCADE)
    basic = models.PositiveIntegerField(verbose_name="Basic Salary"  , default= 0)
    set_deduction_rules = models.BooleanField(verbose_name="Set Deduction Rules" , default=True)
    deduction_rules = models.ManyToManyField(DeductionRules,verbose_name="Deduction Rules" , blank=True , limit_choices_to={"is_global":False})
    set_global_commission_rules = models.BooleanField(verbose_name="Set Global Rule" , default=True)
    commission_rules = models.ManyToManyField(TargetSlice,verbose_name="Commission Target Slices" , blank=True , limit_choices_to={"is_global":False})
    will_arrive_at = models.TimeField(verbose_name="Must Arrive At",default=datetime.time(9,0,0))
    will_leave_at = models.TimeField(verbose_name="Must Leave At",default=datetime.time(17,0,0))

    def __str__(self):
        return f"{self.user} - {self.set_global_commission_rules} - {self.set_deduction_rules}"

    class Meta:
        verbose_name = 'User Commission Details'
        verbose_name_plural = 'User Commission Details'



class Team(BaseModel):
    name = models.CharField(verbose_name="Team Name", max_length=100)
    leader =  models.ForeignKey(User,verbose_name="Leader" , related_name="team_leader", on_delete=models.SET_NULL , null=True)
    agents = models.ManyToManyField(User,verbose_name="Agents" , related_name="team_agents")
    commission_rules = models.ManyToManyField(TargetSlice,verbose_name="Commission Rules")
    def __str__(self):
        return self.name



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
    project = models.ForeignKey(Project,verbose_name="Project" , on_delete=models.SET_NULL , null=True)
    # user_commission_details = models.ForeignKey(UserCommissionDetails, verbose_name="User Commission Details", on_delete=models.SET_NULL , null=True)
    deduction_days = models.FloatField(verbose_name="Deduction Days" , default=0)
    deduction_money = models.IntegerField(verbose_name="Deduction Money" , default=0)
    kpi = models.FloatField(verbose_name="KPI" , default=0)
    gift = models.FloatField(verbose_name="Gift" , default=0)
    basic = models.FloatField(verbose_name="Taken Basic" , default=0)
    date  = models.DateField(verbose_name="Date" , default=now )

    def save(self, *args , **kwargs):
        if self.project is not None and self.user is not None:
            self.project = self.user.project
        return super().save(*args , **kwargs)
    
    def __str__(self):
        return self.date.strftime("%Y/%m")

    class Meta:
        unique_together = ["date","user"]


class Commission(BaseModel):
    user = models.ForeignKey(User, verbose_name="User", on_delete=models.SET_NULL , null=True)
    basic = models.ForeignKey(BasicRecord,verbose_name="Basic" , on_delete=models.SET_NULL , null=True)
    target_count = models.IntegerField(verbose_name="Target Count" , default=0)
    target = models.FloatField(verbose_name="Target" , default=0 )
    target_Team_count = models.IntegerField(verbose_name="Target Team Count" , default=0)
    target_Team = models.FloatField(verbose_name="Target Team" , default=0)
    plus_count = models.IntegerField(verbose_name="Plus Count" , default=0)
    plus = models.FloatField(verbose_name="Plus +5" , default=0)
    plus_10_count = models.IntegerField(verbose_name="Plus 10 Count" , default=0)
    plus_10 = models.FloatField(verbose_name="Plus +10" , default=0)
    american = models.FloatField(verbose_name="American Leads" , default=0)
    american_count = models.IntegerField(verbose_name="American Leads Count" , default=0)
    subscriptions = models.FloatField(verbose_name="Subscriptions" , default=0)
    subscriptions_count = models.IntegerField(verbose_name="Subscriptions Count" , default=0)
    american_subscriptions = models.FloatField(verbose_name="American Subscriptions" , default=0)
    american_subscriptions_count = models.IntegerField(verbose_name="Amirecan Subscriptions Count" , default=0)
    deduction = models.FloatField(verbose_name="Deduction" , default=0)
    gift = models.FloatField(verbose_name="Gift" , default=0)
    salary = models.FloatField(verbose_name="Total of Salary" , default=0)
    date  = models.DateField(verbose_name="Date" , default=now )
    project = models.ForeignKey(Project,verbose_name="Project" , on_delete=models.SET_NULL , null=True)

    def save(self, *args , **kwargs):
        if self.project is not None and self.basic is not None:
            self.project = self.basic.project
        print(args , kwargs)
        return super().save(*args , **kwargs)
    
    def __str__(self):
        return self.date.strftime("%Y/%m")

    class Meta:
        unique_together = ["date","user"]
        
        

class Subscription(BaseModel):
    count = models.IntegerField(verbose_name="Subscriptions Count",unique=True)
    value = models.IntegerField(verbose_name="Money" )

class AmericanSubscription(BaseModel):
    count = models.IntegerField(verbose_name="American Subscriptions Count",unique=True)
    value = models.IntegerField(verbose_name="Money" )


class ActionPlan(BaseModel):
    user = models.ForeignKey(User, verbose_name="User", on_delete=models.SET_NULL , null=True)
    name = models.CharField(verbose_name="Action Plan Name", max_length=100)
    description = models.TextField(verbose_name="Description")
    date = models.DateField(verbose_name="Date", default=now )
    deduction_days = models.FloatField(verbose_name="Deduction Days")
    creator = models.ForeignKey(User, verbose_name="Creator", on_delete=models.SET_NULL,related_name="creator" , null=True)



class Additional(BaseModel):
    plus = models.IntegerField(verbose_name="Plus +5 Price"  , default=50)
    plus_10 = models.IntegerField(verbose_name="Plus +10 Price" , default=100)
    american_leads = models.IntegerField(verbose_name="American Leads Price" )


class Rule(BaseModel):
    class Types(models.TextChoices):
        FROM_TO_MONEY = "ftm","FROM TO MONEY"
        MORE_THAN_MONEY = "mtm" , "MORE THAN MONEY"
        BEST_MONEY = "bm" , "BEST MONEY"
        BEST_MORE_THAN_MONEY = "bmtm" , "BEST MORE THAN MONEY"

    money = models.IntegerField()
    type = models.CharField(max_length=6,choices=Types.choices ,default=Types.FROM_TO_MONEY)
    count_from = models.IntegerField()
    count_to = models.IntegerField()
    more_than = models.IntegerField()
    best_index = models.IntegerField()


class Deal(BaseModel):
    start_at = models.DateField()
    end_at = models.DateField()
    period = models.IntegerField()
    rules = models.ManyToManyField(Rule)
    # agents = 
    ...


def create_user_commission_details(sender, instance:User, created ,**kwargs):
    if created :
        details = UserCommissionDetails.objects.create(
            user=instance ,
            basic=kwargs.get('basic',0),
            set_deduction_rules=kwargs.get('set_deduction_rules',True),
            set_global_commission_rules=kwargs.get('set_global_commission_rules',True),
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


def calc_annual(sender:BaseModel, instance:BasicRecord ,**kwargs):
    try :
        old:BasicRecord = sender.objects.get(uuid=instance.uuid)
        diff = old.take_annual - instance.take_annual
        instance.user.annual_count = instance.user.annual_count + diff 
    except BasicRecord.DoesNotExist:        
        if instance.take_annual > 0 :
            if instance.user.annual_count > instance.take_annual :
                instance.user.annual_count -= instance.take_annual
            else :
                instance.take_annual = instance.user.annual_count
                instance.user.annual_count = 0
    instance.user.save()

        
def delete_annual(sender:BaseModel, instance:BasicRecord, **kwargs):
    if instance.take_annual > 0 :
        instance.user.annual_count =  instance.user.annual_count + instance.take_annual
        instance.user.save()
        


def notify_action_plan(sender, instance:ActionPlan, created ,**kwargs):
    if created :
        notify(f"{instance.creator} عندك جزاء من",instance.user)
    

def notify_request_change(sender, instance:Request, created ,**kwargs):
    if not created and (instance.status == RequestStatuses.ACCEPTED or instance.status == RequestStatuses.REJECTED) :
        notify(f"ريكويست : '{instance.details}' {instance.status} تم تغيير حالة الريكويست الى ",instance.user)
        

def recalculate_salary(sender, instance:BasicRecord, **kwargs):
    try:
        commission = Commission.objects.get(basic=instance)
        # Recalculate the salary field based on the updated BasicRecord instance
        commission.salary = (commission.target + commission.target_Team + commission.plus + 
                             commission.american + commission.subscriptions + commission.american_subscriptions - 
                             commission.deduction + commission.gift + commission.plus_10 + instance.basic)
        commission.save()
    except Commission.DoesNotExist:
        # If no related Commission instance exists, do nothing
        pass

post_save.connect(recalculate_salary, sender=BasicRecord)

pre_save.connect(create_update_history,sender=Team)
pre_save.connect(create_update_history,sender=CoinChanger)
pre_save.connect(create_update_history, sender=TargetSlice)
pre_save.connect(create_update_history, sender=DeductionRules)
pre_save.connect(create_update_history, sender=UserCommissionDetails)
pre_save.connect(create_update_history, sender=Team)
pre_save.connect(create_update_history, sender=CoinChanger)
pre_save.connect(create_update_history, sender=BasicRecord)
pre_save.connect(create_update_history, sender=Commission)
pre_save.connect(calc_annual, sender=BasicRecord)
post_delete.connect(delete_annual,sender=BasicRecord)
post_save.connect(create_user_commission_details,sender=User)
# post_save.connect(create_Outcome_record,sender=BasicRecord)
# post_save.connect(create_Outcome_record_salary,sender=Commission)


post_save.connect(notify_action_plan,sender=ActionPlan)
post_save.connect(notify_request_change,sender=Request)