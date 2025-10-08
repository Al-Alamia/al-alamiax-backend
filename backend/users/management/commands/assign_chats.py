
import time
from django.core.management.base import BaseCommand
from django.utils import timezone
from users.models import User, WhatsappNumber, ArrivingLeaving

class Command(BaseCommand):
    help = 'Periodically assign WhatsApp chats to available sales users.'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Starting chat assignment process...'))

        while True:
            now = timezone.now()
            today = now.date()
            
            # Filter users by role='sales' and who have an arriving record for today
            eligible_users = User.objects.filter(
                role='sales',
                arrivingleaving__date=today
            ).distinct()

            if not eligible_users.exists():
                self.stdout.write(self.style.WARNING('No eligible sales users found. Waiting...'))
                time.sleep(60)
                continue

            unassigned_chats = WhatsappNumber.objects.filter(user__isnull=True)
            if not unassigned_chats.exists():
                self.stdout.write(self.style.SUCCESS('No unassigned chats. Waiting...'))
                time.sleep(60)
                continue

            assigned_stats = {user.username: 0 for user in eligible_users}

            if now.hour < 10:
                # Before 10 AM: Assign one chat to each eligible user
                self.stdout.write(self.style.NOTICE('Before 10 AM: Assigning one chat per user.'))
                for user in eligible_users:
                    chat_to_assign = unassigned_chats.first()
                    if chat_to_assign:
                        chat_to_assign.user = user
                        chat_to_assign.save()
                        assigned_stats[user.username] += 1
                        self.stdout.write(self.style.SUCCESS(f'Assigned chat {chat_to_assign.phone} to {user.username}'))
                        unassigned_chats = unassigned_chats.exclude(pk=chat_to_assign.pk)
                    else:
                        self.stdout.write(self.style.SUCCESS('No more unassigned chats.'))
                        break
            else:
                # After 10 AM: Assign all unassigned chats periodically
                self.stdout.write(self.style.NOTICE('After 10 AM: Assigning all unassigned chats.'))
                user_iterator = iter(eligible_users)
                for chat in unassigned_chats:
                    try:
                        user = next(user_iterator)
                    except StopIteration:
                        user_iterator = iter(eligible_users)
                        user = next(user_iterator)
                    
                    chat.user = user
                    chat.save()
                    assigned_stats[user.username] += 1
                    self.stdout.write(self.style.SUCCESS(f'Assigned chat {chat.phone} to {user.username}'))

            self.stdout.write(self.style.SUCCESS('Assignment round complete. Stats:'))
            for user, count in assigned_stats.items():
                self.stdout.write(f'  {user}: {count} chats')

            # Wait for some time before the next iteration
            time.sleep(300)  # 5 minutes
