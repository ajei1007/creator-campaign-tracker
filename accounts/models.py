from django.contrib.auth.models import AbstractUser
from django.db import models


class Role(models.TextChoices):
    ADMIN = "admin", "Admin"
    MANAGER = "manager", "Campaign Manager"
    REVIEWER = "reviewer", "Reviewer"


class User(AbstractUser):
    """Staff user of the admin. The role drives what the admin exposes.

    Django groups/permissions remain the real enforcement layer the admin
    honours automatically; role is the high-level label we gate custom
    behaviour on (custom actions, read-only fields, the portal).
    """

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.REVIEWER,
        help_text="Determines which campaign tools and payment actions this user can reach.",
    )

    @property
    def is_manager(self):
        return self.role == Role.MANAGER or self.is_superuser

    @property
    def is_reviewer(self):
        return self.role == Role.REVIEWER

    @property
    def can_manage_payments(self):
        return self.role in {Role.ADMIN, Role.MANAGER} or self.is_superuser
