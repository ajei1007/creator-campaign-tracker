import random
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from faker import Faker

from accounts.groups import sync_role_groups
from accounts.models import Role
from campaigns.models import (
    Campaign,
    Creator,
    Niche,
    Participation,
    Platform,
    SocialAccount,
)

fake = Faker()
User = get_user_model()

DEMO_PASSWORD = "demo-pass-1234"

# A curated set of target markets rather than Faker's full country list, so the
# admin's country filter stays a short, usable dropdown instead of 50+ rows.
COUNTRIES = [
    "United States", "United Kingdom", "Canada", "Germany", "France",
    "Brazil", "India", "Australia", "Japan", "Mexico",
]


class Command(BaseCommand):
    help = "Reset and reseed the database with realistic demo data."

    def add_arguments(self, parser):
        parser.add_argument("--creators", type=int, default=60)
        parser.add_argument("--campaigns", type=int, default=16)
        parser.add_argument("--keep", action="store_true", help="Append instead of wiping first.")

    @transaction.atomic
    def handle(self, *args, **opts):
        if not opts["keep"]:
            Participation.objects.all().delete()
            SocialAccount.objects.all().delete()
            Campaign.objects.all().delete()
            Creator.objects.all().delete()
            User.objects.filter(is_superuser=False).delete()

        self._seed_users()
        creators = self._seed_creators(opts["creators"])
        self._seed_campaigns(opts["campaigns"], creators)

        self.stdout.write(self.style.SUCCESS(
            f"Seeded {Creator.objects.count()} creators, "
            f"{SocialAccount.objects.count()} social accounts, "
            f"{Campaign.objects.count()} campaigns, "
            f"{Participation.objects.count()} participations."
        ))
        self.stdout.write("Demo logins (password '%s'):" % DEMO_PASSWORD)
        self.stdout.write("  admin_demo / manager_demo / reviewer_demo")

    def _seed_users(self):
        manager_group, reviewer_group = sync_role_groups()

        admin = self._user("admin_demo", Role.ADMIN, staff=True, superuser=True)
        manager = self._user("manager_demo", Role.MANAGER, staff=True)
        manager.groups.set([manager_group])
        reviewer = self._user("reviewer_demo", Role.REVIEWER, staff=True)
        reviewer.groups.set([reviewer_group])

    def _user(self, username, role, staff=False, superuser=False):
        user, created = User.objects.get_or_create(
            username=username,
            defaults={"email": f"{username}@example.com", "role": role},
        )
        user.role = role
        user.is_staff = staff
        user.is_superuser = superuser
        if created:
            user.set_password(DEMO_PASSWORD)
        user.save()
        return user

    def _seed_creators(self, n):
        creators = []
        niches = [c.value for c in Niche]
        for _ in range(n):
            name = fake.user_name()
            creator = Creator.objects.create(
                display_name=name,
                email=fake.unique.email(),
                country=random.choice(COUNTRIES),
                niche=random.choice(niches),
                bio=fake.sentence(nb_words=16),
            )
            for platform in random.sample([p.value for p in Platform], k=random.randint(1, 3)):
                followers = random.randint(2_000, 3_000_000)
                SocialAccount.objects.create(
                    creator=creator,
                    platform=platform,
                    handle=f"{name}_{platform[:2]}",
                    url=f"https://{platform}.com/{name}",
                    followers=followers,
                    avg_views=int(followers * random.uniform(0.05, 0.5)),
                    avg_likes=int(followers * random.uniform(0.01, 0.08)),
                    avg_comments=int(followers * random.uniform(0.0005, 0.005)),
                    verified=random.random() < 0.25,
                    last_synced=timezone.now() - timedelta(hours=random.randint(1, 72)),
                )
            creators.append(creator)
        return creators

    def _seed_campaigns(self, n, creators):
        brands = ["Lumio", "NovaFit", "ByteBrew", "Everglow", "PixelPeak",
                  "Trailhead", "Snackbox", "Zephyr Audio", "Clariti", "Mintwave"]
        status_pool = (
            [Campaign.Status.ACTIVE] * 6
            + [Campaign.Status.DRAFT] * 3
            + [Campaign.Status.COMPLETED] * 2
            + [Campaign.Status.ARCHIVED]
        )
        for _ in range(n):
            start = timezone.now().date() - timedelta(days=random.randint(-20, 90))
            campaign = Campaign.objects.create(
                name=f"{fake.catch_phrase()[:40]} Launch",
                brand=random.choice(brands),
                status=random.choice(status_pool),
                budget=Decimal(random.randint(8, 60) * 1000),
                max_creators=random.randint(6, 20),
                description=fake.paragraph(nb_sentences=4),
                start_date=start,
                end_date=start + timedelta(days=random.randint(21, 90)),
            )
            self._seed_participations(campaign, creators)

    def _seed_participations(self, campaign, creators):
        # Keep committed spend inside budget by filling only part of the slots.
        target = random.randint(3, max(3, campaign.max_creators - 2))
        chosen = random.sample(creators, k=min(target, len(creators)))
        budget_left = campaign.budget
        for creator in chosen:
            status = self._pick_status(campaign.status)
            fee = Decimal(0)
            if status not in (Participation.Status.INVITED, Participation.Status.DECLINED):
                fee = Decimal(random.randint(2, 15) * 100)
                if status != Participation.Status.REJECTED:
                    if fee > budget_left:
                        continue
                    budget_left -= fee
            p = Participation(
                campaign=campaign,
                creator=creator,
                status=status,
                agreed_fee=fee,
                content_url="https://example.com/post" if status in (
                    Participation.Status.SUBMITTED,
                    Participation.Status.APPROVED,
                    Participation.Status.PAID,
                ) else "",
                notes=fake.sentence() if random.random() < 0.3 else "",
            )
            now = timezone.now()
            if status in (Participation.Status.SUBMITTED, Participation.Status.APPROVED, Participation.Status.PAID):
                p.submitted_at = now - timedelta(days=random.randint(2, 10))
            if status in (Participation.Status.APPROVED, Participation.Status.PAID):
                p.approved_at = now - timedelta(days=random.randint(1, 4))
            if status == Participation.Status.PAID:
                p.paid_at = now - timedelta(days=random.randint(0, 2))
            p.save()

    @staticmethod
    def _pick_status(campaign_status):
        if campaign_status == Campaign.Status.DRAFT:
            return Participation.Status.INVITED
        if campaign_status == Campaign.Status.COMPLETED:
            return random.choice([Participation.Status.PAID, Participation.Status.PAID, Participation.Status.DECLINED])
        return random.choice([
            Participation.Status.INVITED,
            Participation.Status.ACCEPTED,
            Participation.Status.SUBMITTED,
            Participation.Status.APPROVED,
            Participation.Status.PAID,
            Participation.Status.DECLINED,
            Participation.Status.REJECTED,
        ])
