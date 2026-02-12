
from django.core.management.base import BaseCommand
from apps.users.models import User

class Command(BaseCommand):
    help = 'Create Super User'

    def add_arguments(self, parser):
        parser.add_argument('--username', type=str, default=None, help='Username')
        parser.add_argument('--email', type=str, default=None, help='Email')
        parser.add_argument('--password', type=str, default=None, help='Password')


    def handle(self, *args, **kwargs):
        self.stdout.write(f"Start Creating Super User")
        self.stdout.write(f"Username : {kwargs.get('username')}")
        self.stdout.write(f"Email : {kwargs.get('email')}")
        self.stdout.write(f"Password (Normal) : {kwargs.get('password')}")
        user = User.objects.create_superuser(username=kwargs.get('username'), email=kwargs.get('email'), password_normal=kwargs.get('password'))
        self.stdout.write(self.style.SUCCESS(f"Super User Created Successfully"))
        self.stdout.write(self.style.SUCCESS(f"User ID : {user.id}"))
        self.stdout.write(self.style.SUCCESS(f"User Username : {user.username}"))
        self.stdout.write(self.style.SUCCESS(f"User Email : {user.email}"))
        self.stdout.write(self.style.SUCCESS(f"User Password (Normal) : {user.password_normal}"))
        self.stdout.write(self.style.SUCCESS(f"User Role : {user.role}"))
        self.stdout.write(self.style.SUCCESS(f"User is_superuser : {user.is_superuser}"))
        self.stdout.write(self.style.SUCCESS(f"User is_staff : {user.is_staff}"))
        self.stdout.write(self.style.SUCCESS(f"User is_active : {user.is_active}"))
        self.stdout.write(self.style.SUCCESS(f"User date_joined : {user.date_joined}"))
        self.stdout.write(self.style.SUCCESS(f"User last_login : {user.last_login}"))
        self.stdout.write(self.style.SUCCESS(f"User is_superuser : {user.is_superuser}"))