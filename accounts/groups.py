# Sets up the Manager and Reviewer groups with their permissions. Run from the
# seed command, and safe to run again.
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType

from .models import Role


def _perms(model, actions):
    ct = ContentType.objects.get(app_label="campaigns", model=model)
    return list(
        Permission.objects.filter(content_type=ct, codename__in=[f"{a}_{model}" for a in actions])
    )


def sync_role_groups():
    manager, _ = Group.objects.get_or_create(name=Role.MANAGER.label)
    reviewer, _ = Group.objects.get_or_create(name=Role.REVIEWER.label)

    manager_perms = []
    for model in ("campaign", "creator", "socialaccount", "participation"):
        manager_perms += _perms(model, ["add", "change", "view", "delete"])
    manager.permissions.set(manager_perms)

    # Reviewers can view everything and change participations, nothing else.
    reviewer_perms = []
    for model in ("campaign", "creator", "socialaccount", "participation"):
        reviewer_perms += _perms(model, ["view"])
    reviewer_perms += _perms("participation", ["change"])
    reviewer.permissions.set(reviewer_perms)

    return manager, reviewer
