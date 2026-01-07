from apps.users.models import (
    User ,
    Project , 
    Department , 
    ArrivingLeaving ,
    Profile,
    Lead,
)
from apps.commission.models import (
    UserCommissionDetails , 
    DeductionRules,
    TargetSlice,
    Department
)
from datetime import datetime
from typing import List


class Calculator(object):
    def calc_deuration(self,obj:ArrivingLeaving):
        if obj.leaving_at :
            return int(round((obj.leaving_at - obj.arriving_at).total_seconds(),0))
        return 0  # Return lateness in seconds

    def calc_late(self,obj:ArrivingLeaving):
        details:UserCommissionDetails = obj.user.usercommissiondetails
        company_start_time = datetime.combine(datetime.today(), details.will_arrive_at)
        arrival_time = datetime.combine(datetime.today(), obj.arriving_at.time())
        if arrival_time > company_start_time:
            lateness = arrival_time - company_start_time
            return int(round(lateness.total_seconds(),0))  # Return lateness in seconds
        return 0

    def calc_departure(self,obj:ArrivingLeaving):
        details:UserCommissionDetails = obj.user.usercommissiondetails
        company_end_time = datetime.combine(datetime.today(), details.will_leave_at)
        if obj.leaving_at :
            leaving_time = datetime.combine(datetime.today(), obj.leaving_at.time())
            if company_end_time > leaving_time :
                departureness = company_end_time - leaving_time
                return int(round(departureness.total_seconds(),0))  # Return lateness in seconds
        return 0

    def calc_deduction(self,late_time:int , rules:List[DeductionRules]):
        total_deduction = 0
        for rule in rules:
            if not (late_time < rule.late_time):
                total_deduction += rule.deduction_days
                break
        return total_deduction

    def calc_global_deduction(self,late_time:int):
        rules = DeductionRules.objects.filter(is_global=True).order_by("-late_time")
        return self.calc_deduction(late_time,rules)

    def calc_custom_deduction(self,late_time:int,usercommissiondetails:UserCommissionDetails):
        return self.calc_deduction(late_time,usercommissiondetails.deduction_rules.order_by('-late_time').filter())
