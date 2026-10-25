from django.db import IntegrityError, transaction

from apps.notifications.models import Notification, NotificationRecipient
from apps.users.tests.base import BaseUserTestCase


class NotificationModelTests(BaseUserTestCase):
    def test_recipient_unique_per_user(self):
        n = Notification.objects.create(message="hello", sender=self.superuser)
        NotificationRecipient.objects.create(notification=n, user=self.agent)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                NotificationRecipient.objects.create(notification=n, user=self.agent)

    def test_treasury_notification_routes_gone(self):
        self.authenticate_as(self.superuser)
        self.assertEqual(self.client.get("/api/treasury/notifications").status_code, 404)
        self.assertEqual(self.client.get("/api/treasury/my-notification").status_code, 404)
        self.assertEqual(self.client.post("/api/treasury/seen-notification").status_code, 404)
