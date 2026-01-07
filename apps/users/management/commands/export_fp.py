
from datetime import datetime
from typing import List
from django.core.management.base import BaseCommand
from zk import ZK, const
from pandas import DataFrame , date_range
from zk.attendance import Attendance
from zk.user import User as ZkUser
from django.conf import settings
from pathlib import Path
from users.models import ZKConfig


class Command(BaseCommand):
    help = 'Export tasks'

    def add_arguments(self, parser):
        zkconfig = ZKConfig.objects.filter(is_default=True).first()
        parser.add_argument('--ip', type=str, default="192.168.11.157" if not zkconfig else zkconfig.ip, help='ZK IPAddress')
        parser.add_argument('--port', type=int, default=4370 if not zkconfig else zkconfig.port, help='ZK Port')
        parser.add_argument('--timeout', type=int, default=0 if not zkconfig else zkconfig.timeout, help='ZK Timeout Connection')
        parser.add_argument('--password', type=str, default=0 if not zkconfig else zkconfig.password, help='ZK password')
        parser.add_argument('--attendance', action='store_true', help='Export Attendance')
        parser.add_argument('--users', action='store_true', help='Export Users')
        parser.add_argument('--merged', action='store_true', help='Export Merged Data')
        parser.add_argument('--path', type=str, default=str(settings.BASE_DIR)+"\\Exports", help='ZK Port')

    def handle(self, *args, **kwargs):
        self.stdout.write(f"Start Zk FP Syncing on")
        self.stdout.write(f"IP/Port : {kwargs.get('ip')}:{kwargs.get('port')}")
        conn = None
        zk = ZK(kwargs.get("ip"), port=kwargs.get("port"), timeout=kwargs.get("timeout"), password=kwargs.get("password"), force_udp=False, ommit_ping=False)
        try : 
            conn = zk.connect()
            self.stdout.write(self.style.SUCCESS(f"Successfully Connected to Zk Serial : {conn.get_serialnumber()} "))
            conn.disable_device()
            self.stdout.write(self.style.SUCCESS(f"Disabled other activity ..."))
            if kwargs.get("attendance") or kwargs.get("merged"):
                attendance:List[Attendance] = conn.get_attendance() 
            if kwargs.get("users") or kwargs.get("merged"):
                users:List[ZkUser] = conn.get_users()
            serial = conn.get_serialnumber()
            conn.enable_device()
            self.stdout.write(self.style.SUCCESS(f"Enable activity again ..."))
            if conn:
                conn.disconnect()
                self.stdout.write(self.style.SUCCESS(f"Disconnected Success !"))
                conn = None
            path = Path(kwargs.get("path"))
            if not path.exists():
                path.mkdir(parents=True, exist_ok=True)

            if kwargs.get("attendance"):
                df = self.export_attendance(attendance)
                df.to_excel(f"{path}\\{serial}-attendance-{datetime.now().date()}.xlsx",index=False)
            if kwargs.get("users"):
                df = self.export_users(users)
                df.to_excel(f"{path}\\{serial}-users-{datetime.now().date()}.xlsx",index=False)
            if kwargs.get("merged"):
                df = self.export_merged(users,attendance)
                df.to_excel(f"{path}\\{serial}-merged-{datetime.now().date()}.xlsx",index=False)
                
            self.stdout.write(self.style.SUCCESS(f"Exported Tasks Success to '{path}' !"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Process terminate : {e}"))
        finally:
            if conn:
                conn.disconnect()
                self.stdout.write(self.style.SUCCESS(f"Disconnected Success !"))

        
    def export_attendance(self,attendance:List[Attendance])-> DataFrame:
        self.stdout.write(self.style.SUCCESS(f"Attendance Loaded : {len(attendance)} ..."))
        self.stdout.write(self.style.SUCCESS(f"Creating Dataframe to make Export ... "))
        df = DataFrame(data=attendance,columns=["attendance"])
        df['user_id'] = df["attendance"].map(lambda attend:attend.user_id)
        df['uid'] = df["attendance"].map(lambda attend:attend.uid)
        df['timestamp'] = df["attendance"].map(lambda attend:attend.timestamp)
        df['status'] = df["attendance"].map(lambda attend:attend.status)
        df['punch'] = df["attendance"].map(lambda attend: "Out" if attend.punch else "In")
        self.stdout.write(self.style.SUCCESS(f"Successfully getted Attendance FP Dataframe "))
        return df
    
    def export_merged(self,users:List[ZkUser],attendance:List[Attendance])-> DataFrame:
        self.stdout.write(self.style.SUCCESS(f"Attendance Loaded : {len(attendance)} ..."))
        self.stdout.write(self.style.SUCCESS(f"Creating Dataframe to make Export ... "))
        df = DataFrame(data=attendance,columns=["attendance"])
        df['uid'] = df["attendance"].map(lambda attend:attend.uid)
        df['user_id'] = df["attendance"].map(lambda attend:attend.user_id)
        df['user_uid'] = df["attendance"].map(lambda attend:self.__filter_uid(attend,users))
        df['username'] = df["attendance"].map(lambda a :self.__filter_name(a,users))
        df['timestamp'] = df["attendance"].map(lambda attend:attend.timestamp)
        df['status'] = df["attendance"].map(lambda attend:attend.status)
        df['punch'] = df["attendance"].map(lambda attend: "Out" if attend.punch else "In")
        self.stdout.write(self.style.SUCCESS(f"Successfully getted Merged FP Dataframe "))
        return df
    
    def __filter_name(self,attend:Attendance , users):
        result = list(filter(lambda usr:usr.user_id == attend.user_id,users))
        if result :
            return result[0].name
        return "-"   
         
    def __filter_uid(self,attend:Attendance , users):
        result = list(filter(lambda usr:usr.user_id == attend.user_id,users))
        if result :
            return result[0].uid
        return "-"        
    
    def export_users(self,users:List[ZkUser])-> DataFrame:
        self.stdout.write(self.style.SUCCESS(f"Users Loaded : {len(users)} ..."))
        self.stdout.write(self.style.SUCCESS(f"Creating Dataframe to make Export ... "))
        df = DataFrame(data=users,columns=["user"])
        users[0].password
        df['user_id'] = df["user"].map(lambda usr:usr.user_id)
        df['uid'] = df["user"].map(lambda usr:usr.uid)
        df['name'] = df["user"].map(lambda usr:usr.name)
        df['privilege'] = df["user"].map(lambda usr:usr.privilege)
        df['password'] = df["user"].map(lambda usr:usr.password)
        self.stdout.write(self.style.SUCCESS(f"Successfully getted Users FP Dataframe "))
        return df
    
    