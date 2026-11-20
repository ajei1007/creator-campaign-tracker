from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from .models import Campaign, Creator, Participation, SocialAccount


def make_campaign(**kwargs):
    defaults = dict(
        name="Test Campaign",
        brand="Acme",
        status=Campaign.Status.ACTIVE,
        budget=Decimal("1000"),
        max_creators=3,
        start_date=timezone.now().date(),
        end_date=timezone.now().date() + timedelta(days=30),
    )
    defaults.update(kwargs)
    return Campaign.objects.create(**defaults)


class EngagementRateTests(TestCase):
    def test_rate_is_engagements_over_followers(self):
        creator = Creator.objects.create(display_name="c", email="c@example.com")
        acc = SocialAccount.objects.create(
            creator=creator, platform="instagram", handle="c",
            followers=1000, avg_likes=80, avg_comments=20,
        )
        self.assertEqual(acc.engagement_rate, Decimal("10.00"))

    def test_zero_followers_is_zero_not_crash(self):
        creator = Creator.objects.create(display_name="c", email="c2@example.com")
        acc = SocialAccount.objects.create(
            creator=creator, platform="tiktok", handle="c2", followers=0, avg_likes=5,
        )
        self.assertEqual(acc.engagement_rate, Decimal("0.00"))


class StatusTransitionTests(TestCase):
    def setUp(self):
        self.campaign = make_campaign()
        self.creator = Creator.objects.create(display_name="c", email="c@example.com")

    def _p(self, status):
        p = Participation.objects.create(
            campaign=self.campaign, creator=self.creator, status=Participation.Status.INVITED
        )
        p.status = status
        return p

    def test_legal_transition_passes(self):
        p = self._p(Participation.Status.ACCEPTED)
        p.full_clean(exclude=["campaign", "creator"])  # should not raise

    def test_illegal_skip_is_rejected(self):
        p = self._p(Participation.Status.PAID)
        with self.assertRaises(ValidationError) as ctx:
            p.full_clean(exclude=["campaign", "creator"])
        self.assertIn("status", ctx.exception.message_dict)

    def test_declined_is_terminal(self):
        p = Participation.objects.create(
            campaign=self.campaign, creator=self.creator, status=Participation.Status.INVITED
        )
        p.status = Participation.Status.DECLINED
        p.save()
        p.status = Participation.Status.ACCEPTED
        with self.assertRaises(ValidationError):
            p.full_clean(exclude=["campaign", "creator"])

    def test_timestamps_set_on_transition(self):
        p = Participation.objects.create(
            campaign=self.campaign, creator=self.creator,
            status=Participation.Status.ACCEPTED, agreed_fee=Decimal("100"),
        )
        self.assertIsNone(p.submitted_at)
        p.status = Participation.Status.SUBMITTED
        p.save()
        self.assertIsNotNone(p.submitted_at)

    def test_paid_requires_a_fee(self):
        p = Participation.objects.create(
            campaign=self.campaign, creator=self.creator, status=Participation.Status.INVITED
        )
        p.status = Participation.Status.ACCEPTED
        p.save()
        p.status = Participation.Status.SUBMITTED
        p.save()
        p.status = Participation.Status.APPROVED
        p.save()
        p.status = Participation.Status.PAID
        p.agreed_fee = Decimal("0")
        with self.assertRaises(ValidationError):
            p.full_clean(exclude=["campaign", "creator"])


class BudgetAndCapacityTests(TestCase):
    def setUp(self):
        self.campaign = make_campaign(budget=Decimal("500"), max_creators=2)

    def _creator(self, i):
        return Creator.objects.create(display_name=f"c{i}", email=f"c{i}@example.com")

    def test_committed_fee_cannot_exceed_budget(self):
        p = Participation.objects.create(
            campaign=self.campaign, creator=self._creator(1),
            status=Participation.Status.ACCEPTED, agreed_fee=Decimal("600"),
        )
        with self.assertRaises(ValidationError) as ctx:
            p.full_clean(exclude=["campaign", "creator"])
        self.assertIn("agreed_fee", ctx.exception.message_dict)

    def test_budget_sums_across_participations(self):
        Participation.objects.create(
            campaign=self.campaign, creator=self._creator(1),
            status=Participation.Status.ACCEPTED, agreed_fee=Decimal("400"),
        )
        p2 = Participation.objects.create(
            campaign=self.campaign, creator=self._creator(2),
            status=Participation.Status.ACCEPTED, agreed_fee=Decimal("200"),
        )
        with self.assertRaises(ValidationError):
            p2.full_clean(exclude=["campaign", "creator"])

    def test_capacity_cap_enforced(self):
        self.campaign.max_creators = 1
        self.campaign.save()
        Participation.objects.create(
            campaign=self.campaign, creator=self._creator(1),
            status=Participation.Status.ACCEPTED, agreed_fee=Decimal("100"),
        )
        p2 = Participation(
            campaign=self.campaign, creator=self._creator(2),
            status=Participation.Status.ACCEPTED, agreed_fee=Decimal("100"),
        )
        with self.assertRaises(ValidationError):
            p2.full_clean(exclude=["campaign", "creator"])

    def test_campaign_budget_remaining(self):
        Participation.objects.create(
            campaign=self.campaign, creator=self._creator(1),
            status=Participation.Status.PAID, agreed_fee=Decimal("150"),
        )
        self.assertEqual(self.campaign.budget_remaining, Decimal("350"))


class CampaignValidationTests(TestCase):
    def test_end_date_must_follow_start(self):
        c = Campaign(
            name="x", brand="y", budget=Decimal("100"),
            start_date=timezone.now().date(),
            end_date=timezone.now().date() - timedelta(days=1),
        )
        with self.assertRaises(ValidationError) as ctx:
            c.clean()
        self.assertIn("end_date", ctx.exception.message_dict)
