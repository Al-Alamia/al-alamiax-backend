from django.core.management.base import BaseCommand
from django.conf import settings
from users.models import WhatsappAccount , WhatsappNumber , ArrivingLeaving
from django.utils import timezone
from users.models import User

class Command(BaseCommand):

    def add_arguments(self, parser): ...



    help = 'Assign WhatsApp numbers to users based on their arrival records'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Starting chat assignment process...'))
        
        
        # Get current time and today's date
        now = timezone.now()
        today = timezone.now().date()
        
        # Get all unassigned WhatsApp numbers
        unassigned_numbers = WhatsappNumber.objects.filter(user__isnull=True)
        self.stdout.write(f'Found {unassigned_numbers.count()} unassigned numbers')
        
        if unassigned_numbers.count() == 0:
            self.stdout.write(self.style.SUCCESS('No unassigned numbers found. Exiting...'))
            return
        
        # Get users who have arrived today
        arrived_users = User.objects.filter(
            arrivingleaving__date=today,
            arrivingleaving__arriving_at__isnull=False
        ).distinct()
        
        self.stdout.write(f'Found {arrived_users.count()} users who have arrived today')
        
        if arrived_users.count() == 0:
            self.stdout.write(self.style.WARNING('No users have arrived today. Exiting...'))
            return
        
        # Check if it's before 10 AM
        is_before_10am = now.hour < 10
        
        if is_before_10am:
            self.stdout.write('Current time is before 10 AM. Assigning one number to one user...')
            # Get the first unassigned number
            number_to_assign = unassigned_numbers.first()
            # Get the first arrived user
            user_to_assign = arrived_users.first()
            
            # Assign the number to the user
            number_to_assign.user = user_to_assign
            number_to_assign.save()
            
            self.stdout.write(
                self.style.SUCCESS(
                    f'Assigned number {number_to_assign.phone} to user {user_to_assign.username}'
                )
            )
        else:
            self.stdout.write('Current time is after 10 AM. Assigning all numbers...')
            
            # Assign numbers to users in a round-robin fashion
            numbers = list(unassigned_numbers)
            users = list(arrived_users)
            
            if not users:
                self.stdout.write(self.style.WARNING('No users available for assignment. Exiting...'))
                return
                
            assignments = 0
            for i, number in enumerate(numbers):
                user = users[i % len(users)]
                number.user = user
                number.save()
                assignments += 1
                self.stdout.write(
                    f'Assigned number {number.phone} to user {user.username}'
                )
            
            self.stdout.write(
                self.style.SUCCESS(f'Successfully assigned {assignments} numbers to users')
            )
        
        self.stdout.write(self.style.SUCCESS('Chat assignment process completed!'))