from io import StringIO

from django.core.management import call_command

from apps.notifications.models import Notification
from apps.penalties.models import Penalty, PenaltyType
from apps.penalties.tests.factories import make_user
from apps.users.tests.base import BaseUserTestCase
from apps.users.types import UserTypes


def seed():
    out = StringIO()
    call_command("seed_penalties_demo", stdout=out)
    return out.getvalue()


class SeedPenaltiesDemoTests(BaseUserTestCase):
    def setUp(self):
        super().setUp()
        self.hr = make_user("seed_hr", UserTypes.HR)
        for i in range(3):
            make_user(f"seed_agent{i}", UserTypes.AGENT)

    def test_seed_creates_types_and_penalties(self):
        seed()
        self.assertEqual(PenaltyType.objects.count(), 4)
        self.assertTrue(PenaltyType.objects.filter(name="Equipment damage", kind="money").exists())
        penalties = Penalty.objects.all()
        self.assertGreaterEqual(penalties.count(), 8)
        self.assertGreaterEqual(penalties.filter(voided_at__isnull=False).count(), 1)
        self.assertTrue(penalties.filter(penalty_type__isnull=True).exists())
        for p in penalties:
            self.assertIn("[demo]", p.description)
            self.assertIn(p.created_by.role, [UserTypes.HR, UserTypes.OWNER])
            self.assertFalse(p.user.is_superuser)
            self.assertNotEqual(p.user, p.created_by)

    def test_seed_idempotent(self):
        seed()
        counts = (PenaltyType.objects.count(), Penalty.objects.count())
        seed()
        self.assertEqual((PenaltyType.objects.count(), Penalty.objects.count()), counts)

    def test_seed_no_notifications(self):
        seed()
        self.assertEqual(Notification.objects.count(), 0)

    def test_seed_without_targets_creates_only_types(self):
        from apps.users.models import User
        User.objects.exclude(pk=self.hr.pk).update(is_active=False)
        out = seed()
        self.assertEqual(PenaltyType.objects.count(), 4)
        self.assertEqual(Penalty.objects.count(), 0)
        self.assertIn("No eligible users", out)
