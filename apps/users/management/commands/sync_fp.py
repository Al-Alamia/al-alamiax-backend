from django.core.management.base import BaseCommand
from zk import ZK, const
from zk.attendance import Attendance
from zk.user import User as ZkUser
from zk.finger import Finger
from typing import Union, List , Tuple
from pandas import DataFrame , date_range
from users.models import User , ArrivingLeaving , ZKConfig
from datetime import timedelta, datetime 
import warnings
from django.db.models import Q

warnings.filterwarnings('ignore')


class Command(BaseCommand):
    help = 'Sync tasks'
    
    
    def add_arguments(self, parser):
        zkconfig = ZKConfig.objects.filter(is_default=True).first()
        parser.add_argument('--ip', type=str, default="192.168.11.157" if not zkconfig else zkconfig.ip, help='ZK IPAddress')
        parser.add_argument('--port', type=int, default=4370 if not zkconfig else zkconfig.port, help='ZK Port')
        parser.add_argument('--timeout', type=int, default=0 if not zkconfig else zkconfig.timeout, help='ZK Timeout Connection')
        parser.add_argument('--password', type=str, default=0 if not zkconfig else zkconfig.password, help='ZK password')
        # parser.add_argument('--user', type=str, default=None, help='ZK Sync Exact User')
        now = datetime.now().date()
        curr = now.day
        now = datetime(now.year,now.month,day=25).date()
        to = now - timedelta(days=31 * (1 if curr <= 25 else -1) )
        l = datetime(to.year,to.month,day=25).date()
        parser.add_argument('--date', type=str, default=f"{min(now,l)}~{max(now,l)}", help='Extract from date to date like "2024-8-25~2024-9-25"')


    def handle(self, *args, **kwargs):
        dates = [datetime.strptime(t,"%Y-%m-%d").date() for t in kwargs.get('date').split('~')]
        date_from = min(dates)
        date_to = max(dates)
        self.stdout.write(f"Start Zk FP Syncing on")
        self.stdout.write(f"IP/Port : {kwargs.get('ip')}:{kwargs.get('port')}")
        self.stdout.write(f"Date : {date_from} to {date_to}")
        # self.stdout.write(f"User : {kwargs.get('user')}") if kwargs.get('user') else None
        conn = None
        zk = ZK(kwargs.get("ip"), port=kwargs.get("port"), timeout=kwargs.get("timeout"), password=kwargs.get("password"), force_udp=False, ommit_ping=False)
        try : 
            conn = zk.connect()
            self.stdout.write(self.style.SUCCESS(f"Successfully Connected to Zk Serial : {conn.get_serialnumber()} "))
            conn.disable_device()
            self.stdout.write(self.style.SUCCESS(f"Disabled other activity ..."))
            fp_attend_df , zk_users = self._get_attend_with_user(conn)
            fp_attend_df = fp_attend_df[fp_attend_df['date'] >= date_from]
            conn.enable_device()
            self.stdout.write(self.style.SUCCESS(f"Enable activity again ..."))
            if conn:
                conn.disconnect()
                self.stdout.write(self.style.SUCCESS(f"Disconnected Success !"))
                conn = None
            d_range = date_range(start=date_from, end=date_to).strftime('%Y-%m-%d').tolist()
            self.stdout.write(self.style.SUCCESS(f"Created Date Range from : {date_from} || to : {date_to}"))
            users = User.objects.filter(~Q(fp_id='') & Q(fp_id__isnull=False))
            self.stdout.write(self.style.SUCCESS(f"Get Users from ZK Machine count : {users.count()}"))
            
            self._map_update(users,d_range,fp_attend_df)
                
            
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Process terminate : {e}"))
        finally:
            if conn:
                conn.disconnect()
                self.stdout.write(self.style.SUCCESS(f"Disconnected Success !"))
                
        self.stdout.write("Sync Task Ended !")
        


    def _get_attend_with_user(self , conn:ZK ) -> Tuple[DataFrame , List[ZkUser]] :
        attendance:List[Attendance] = conn.get_attendance()
        self.stdout.write(self.style.SUCCESS(f"Attendance Loaded : {len(attendance)} ..."))
        users:List[ZkUser] = conn.get_users()
        self.stdout.write(self.style.SUCCESS(f"Users Loaded : {len(users)} ..."))
        self.stdout.write(self.style.SUCCESS(f"Creating Dataframe to make analytics ... "))
        df = DataFrame(data=attendance,columns=["attendance"])
        df['user_id'] = df["attendance"].map(lambda attend:attend.user_id)
        df['uid'] = df["attendance"].map(lambda attend:attend.uid)
        df['user_uid'] = df["attendance"].map(lambda attend:self.__filter_uid(attend,users))
        df['date'] = df["attendance"].map(lambda attend:attend.timestamp.date())
        df['status'] = df["attendance"].map(lambda attend:attend.status)
        df['punch'] = df["attendance"].map(lambda attend:attend.punch)
        self.stdout.write(self.style.SUCCESS(f"Successfully getted FP Dataframe "))
        return df , users
    
    def __filter_uid(self,attend:Attendance , users):
        result = list(filter(lambda usr:usr.user_id == attend.user_id,users))
        if result :
            return result[0].uid
        return "-"        

    def _map_update(self,users:List[User],d_range:List[datetime],df_attend:DataFrame):
        for user in users :
            # log
            temp_df = df_attend[df_attend["user_id"] == user.fp_id]
            temp_df['date'] = temp_df['date'].apply(str)
            for day in d_range :
                arr_leav = ArrivingLeaving.objects.filter(user=user,date=day).first()
                times = temp_df[temp_df['date'] == day]['attendance'].map(lambda att: att.timestamp).tolist()
                if not times :
                    continue
                elif arr_leav:
                    created = False
                elif not arr_leav :
                    created = True
                    # print(f"\n{user}\n{datetime.strptime(day,'%Y-%m-%d').date()}\n{ArrivingLeaving.objects.filter(user=user,date=day)}\n")
                    arr_leav = ArrivingLeaving(
                        user=user,
                        date=datetime.strptime(day,"%Y-%m-%d").date(),
                    )
                else :
                    self.stdout.write(self.style.ERROR(f"Can't define {arr_leav} and {times}"))
                    continue
                self._update_user_arrive_leave(arr_leav,created,times)
            self.stdout.write(self.style.SUCCESS(f"Success update User -> {user.username} | uid => {user.fp_id} "))
        self.stdout.write(self.style.SUCCESS(f"Success Update => {len(users)} user\nEnd Update users FP  !"))
                        
        
    def _update_user_arrive_leave(self,arr_leav:ArrivingLeaving,created:bool,times:List[Union[datetime,str]]):
        if times :
            arr_leav.arriving_at = min(arr_leav.arriving_at,*times) if not created else min(times)
            # print(arr_leav.leaving_at,*times) if not created and arr_leav.leaving_at else print(times)
            if arr_leav.date != datetime.now().date() and len(times) > 1:
                leaving_at = max(arr_leav.leaving_at,*times) if not created and arr_leav.leaving_at else max(times)
                if leaving_at != arr_leav.arriving_at :
                    arr_leav.leaving_at = leaving_at
            arr_leav.save()
        return arr_leav
        
# df = DataFrame(data=attendance,columns=["Attendance"])
# df['user_id'] = df["Attendance"].map(lambda attend:attend.user_id)
# df['username'] = df["Attendance"].map(lambda attend:list(filter(lambda usr:usr.user_id == attend.user_id,users))[0].name)
# df['timestamp'] = df["Attendance"].map(lambda attend:attend.timestamp)
# df['status'] = df["Attendance"].map(lambda attend:attend.status)
# df['punch'] = df["Attendance"].map(lambda attend:attend.punch)
