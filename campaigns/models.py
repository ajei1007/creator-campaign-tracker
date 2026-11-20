from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Sum
from django.utils import timezone

from .validators import validate_document_upload, validate_image_upload


class Platform(models.TextChoices):
    INSTAGRAM = "instagram", "Instagram"
    YOUTUBE = "youtube", "YouTube"
    TIKTOK = "tiktok", "TikTok"
    TWITCH = "twitch", "Twitch"
    KICK = "kick", "Kick"
    FACEBOOK = "facebook", "Facebook"
    TWITTER = "twitter", "X / Twitter"


class Niche(models.TextChoices):
    GAMING = "gaming", "Gaming"
    BEAUTY = "beauty", "Beauty"
    FITNESS = "fitness", "Fitness"
    TECH = "tech", "Tech"
    FOOD = "food", "Food"
    TRAVEL = "travel", "Travel"
    FASHION = "fashion", "Fashion"
    FINANCE = "finance", "Finance"
    LIFESTYLE = "lifestyle", "Lifestyle"


class Creator(models.Model):
    display_name = models.CharField(max_length=120, help_text="Public handle or name shown to brands.")
    email = models.EmailField(unique=True, help_text="Primary contact; also used to link a portal login.")
    country = models.CharField(max_length=56, blank=True, help_text="ISO country name, used for geo targeting.")
    niche = models.CharField(
        max_length=20,
        choices=Niche.choices,
        default=Niche.LIFESTYLE,
        help_text="Primary content category this creator is booked for.",
    )
    bio = models.TextField(blank=True, help_text="Short pitch shown on the creator's profile.")
    avatar = models.ImageField(
        upload_to="creators/avatars/",
        blank=True,
        null=True,
        validators=[validate_image_upload],
        help_text="Square profile image, max 5 MB (jpg, png, webp, gif).",
    )
    portal_user = models.OneToOneField(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="creator_profile",
        help_text="Optional login that lets this creator see their own campaigns in the portal.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["display_name"]

    def __str__(self):
        return self.display_name

    @property
    def total_followers(self):
        return self.social_accounts.aggregate(n=Sum("followers"))["n"] or 0

    @property
    def active_campaign_count(self):
        return self.participations.exclude(
            status__in=[Participation.Status.DECLINED, Participation.Status.REJECTED]
        ).count()


class SocialAccount(models.Model):
    creator = models.ForeignKey(
        Creator,
        on_delete=models.CASCADE,
        related_name="social_accounts",
        help_text="Owner of this social account.",
    )
    platform = models.CharField(max_length=20, choices=Platform.choices)
    handle = models.CharField(max_length=120, help_text="Username without the @.")
    url = models.URLField(blank=True)
    followers = models.PositiveIntegerField(default=0, help_text="Follower / subscriber count.")
    avg_views = models.PositiveIntegerField(default=0, help_text="Average views per post over the last 30 days.")
    avg_likes = models.PositiveIntegerField(default=0)
    avg_comments = models.PositiveIntegerField(default=0)
    verified = models.BooleanField(default=False)
    last_synced = models.DateTimeField(null=True, blank=True, help_text="When metrics were last pulled.")

    class Meta:
        ordering = ["-followers"]
        constraints = [
            models.UniqueConstraint(
                fields=["platform", "handle"], name="unique_platform_handle"
            )
        ]

    def __str__(self):
        return f"{self.get_platform_display()} @{self.handle}"

    @property
    def engagement_rate(self):
        """Engagements per follower as a percentage. The headline metric brands buy on."""
        if not self.followers:
            return Decimal("0.00")
        rate = (self.avg_likes + self.avg_comments) / self.followers * 100
        return round(Decimal(rate), 2)


def _year_from_now():
    return timezone.now().date().replace(year=timezone.now().year + 1)


class Campaign(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        ACTIVE = "active", "Active"
        COMPLETED = "completed", "Completed"
        ARCHIVED = "archived", "Archived"

    name = models.CharField(max_length=160)
    brand = models.CharField(max_length=120, help_text="Client the campaign runs for.")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    budget = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0"))],
        help_text="Total creator budget in USD. Committed fees may not exceed this.",
    )
    max_creators = models.PositiveIntegerField(
        default=10, help_text="Hard cap on how many creators can be booked onto this campaign."
    )
    description = models.TextField(blank=True, help_text="Brief shown to invited creators.")
    banner = models.ImageField(
        upload_to="campaigns/banners/",
        blank=True,
        null=True,
        validators=[validate_image_upload],
        help_text="Hero image for the campaign, max 5 MB.",
    )
    start_date = models.DateField(help_text="First day creators may post.")
    end_date = models.DateField(help_text="Campaign close date; must be after the start date.")
    creators = models.ManyToManyField(
        Creator, through="Participation", related_name="campaigns", blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.brand})"

    def clean(self):
        if self.start_date and self.end_date and self.end_date <= self.start_date:
            raise ValidationError({"end_date": "End date must be after the start date."})

    @property
    def committed_spend(self):
        """Fees owed to everyone still in the funnel (accepted and beyond)."""
        active = self.participations.exclude(
            status__in=[
                Participation.Status.INVITED,
                Participation.Status.DECLINED,
                Participation.Status.REJECTED,
            ]
        )
        return active.aggregate(n=Sum("agreed_fee"))["n"] or Decimal("0")

    @property
    def paid_spend(self):
        paid = self.participations.filter(status=Participation.Status.PAID)
        return paid.aggregate(n=Sum("agreed_fee"))["n"] or Decimal("0")

    @property
    def budget_remaining(self):
        return self.budget - self.committed_spend

    @property
    def is_over_budget(self):
        return self.committed_spend > self.budget

    @property
    def active_participant_count(self):
        return self.participations.exclude(
            status__in=[Participation.Status.DECLINED, Participation.Status.REJECTED]
        ).count()

    @property
    def slots_remaining(self):
        return max(self.max_creators - self.active_participant_count, 0)


class Participation(models.Model):
    """A creator's booking on a campaign. Carries the status workflow and money.

    Legal transitions:
        invited   -> accepted | declined
        accepted  -> submitted
        submitted -> approved | rejected
        rejected  -> submitted      (creator reworks and resubmits)
        approved  -> paid
    """

    class Status(models.TextChoices):
        INVITED = "invited", "Invited"
        ACCEPTED = "accepted", "Accepted"
        DECLINED = "declined", "Declined"
        SUBMITTED = "submitted", "Content submitted"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        PAID = "paid", "Paid"

    TRANSITIONS = {
        Status.INVITED: {Status.ACCEPTED, Status.DECLINED},
        Status.ACCEPTED: {Status.SUBMITTED},
        Status.SUBMITTED: {Status.APPROVED, Status.REJECTED},
        Status.REJECTED: {Status.SUBMITTED},
        Status.APPROVED: {Status.PAID},
        Status.DECLINED: set(),
        Status.PAID: set(),
    }

    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name="participations")
    creator = models.ForeignKey(Creator, on_delete=models.PROTECT, related_name="participations")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.INVITED)
    agreed_fee = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
        help_text="Flat fee paid to the creator for this campaign, in USD.",
    )
    content_url = models.URLField(blank=True, help_text="Link to the submitted post or video.")
    deliverable = models.FileField(
        upload_to="participations/deliverables/",
        blank=True,
        null=True,
        validators=[validate_document_upload],
        help_text="Optional proof of posting (pdf or image), max 5 MB.",
    )
    notes = models.TextField(blank=True)
    invited_at = models.DateTimeField(auto_now_add=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-invited_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["campaign", "creator"], name="unique_campaign_creator"
            )
        ]

    def __str__(self):
        return f"{self.creator} on {self.campaign.name}"

    @classmethod
    def from_db(cls, db, field_names, values):
        instance = super().from_db(db, field_names, values)
        instance._original_status = instance.status
        return instance

    def can_transition_to(self, new_status):
        current = getattr(self, "_original_status", self.status)
        if new_status == current:
            return True
        return new_status in self.TRANSITIONS.get(current, set())

    def clean(self):
        current = getattr(self, "_original_status", None)
        if current is not None and self.status != current:
            if not self.can_transition_to(self.status):
                raise ValidationError(
                    {"status": f"Cannot move a participation from '{current}' to '{self.status}'."}
                )
        if self.status == self.Status.PAID and self.agreed_fee <= 0:
            raise ValidationError(
                {"agreed_fee": "A fee must be agreed before a creator can be marked as paid."}
            )
        self._validate_capacity()
        self._validate_budget()

    def _validate_capacity(self):
        if self.status in (self.Status.DECLINED, self.Status.REJECTED):
            return
        if not self.campaign_id:
            return
        taken = self.campaign.participations.exclude(pk=self.pk).exclude(
            status__in=[self.Status.DECLINED, self.Status.REJECTED]
        ).count()
        if taken + 1 > self.campaign.max_creators:
            raise ValidationError(
                f"Campaign '{self.campaign.name}' is full "
                f"({self.campaign.max_creators} creator slots)."
            )

    def _validate_budget(self):
        if self.status in (self.Status.INVITED, self.Status.DECLINED, self.Status.REJECTED):
            return
        if not self.campaign_id:
            return
        others = self.campaign.participations.exclude(pk=self.pk).exclude(
            status__in=[self.Status.INVITED, self.Status.DECLINED, self.Status.REJECTED]
        ).aggregate(n=Sum("agreed_fee"))["n"] or Decimal("0")
        if others + self.agreed_fee > self.campaign.budget:
            raise ValidationError(
                {"agreed_fee": (
                    f"Committing ${self.agreed_fee} would exceed the campaign budget "
                    f"of ${self.campaign.budget} (already committed ${others})."
                )}
            )

    def save(self, *args, **kwargs):
        now = timezone.now()
        if self.status == self.Status.SUBMITTED and not self.submitted_at:
            self.submitted_at = now
        if self.status == self.Status.APPROVED and not self.approved_at:
            self.approved_at = now
        if self.status == self.Status.PAID and not self.paid_at:
            self.paid_at = now
        super().save(*args, **kwargs)
        self._original_status = self.status
