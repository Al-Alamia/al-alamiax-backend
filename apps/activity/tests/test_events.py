from datetime import date
from decimal import Decimal

from django.contrib.auth.models import AnonymousUser
from django.db import transaction

from apps.activity.models import ActivityEvent, Area
from apps.activity.services.events import record_event
from apps.activity.verbs import VERBS
from apps.users.tests.base import BaseUserTestCase


class RecordEventTests(BaseUserTestCase):
    def test_area_from_registry(self):
        e = record_event(self.superuser, "request.approved", subject=self.agent, label="x")
        self.assertEqual(e.area, "attendance")
        self.assertEqual(e.actor, self.superuser)
        self.assertEqual(e.subject, self.agent)
        self.assertEqual(e.target_label, "x")

    def test_unknown_verb_raises(self):
        with self.assertRaises(ValueError):
            record_event(self.superuser, "nope.nothing")

    def test_anonymous_actor_stored_null(self):
        e = record_event(AnonymousUser(), "request.approved", subject=None)
        self.assertIsNone(e.actor_id)
        self.assertIsNone(e.subject_id)

    def test_target_fields(self):
        e = record_event(self.superuser, "request.approved", target=self.agent)
        self.assertEqual(e.target_type, "user")
        self.assertEqual(e.target_uuid, self.agent.pk)

    def test_data_jsonable(self):
        e = record_event(self.superuser, "salary.given", data={
            "amount": Decimal("12.50"), "day": date(2026, 11, 8), "nested": {"d": Decimal("1")},
        })
        e.refresh_from_db()
        self.assertEqual(e.data, {"amount": "12.50", "day": "2026-11-08", "nested": {"d": "1"}})

    def test_rollback_leaves_no_event(self):
        try:
            with transaction.atomic():
                record_event(self.superuser, "request.approved")
                raise RuntimeError("boom")
        except RuntimeError:
            pass
        self.assertEqual(ActivityEvent.objects.count(), 0)

    def test_every_verb_has_valid_area(self):
        for verb, area in VERBS.items():
            self.assertIn(area, Area.values, verb)
        self.assertEqual(len(VERBS), 59)
