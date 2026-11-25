from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render


@login_required
def home(request):
    # Staff go to the admin; a linked creator sees their own campaigns.
    user = request.user
    if user.is_staff:
        return redirect("admin:index")

    profile = getattr(user, "creator_profile", None)
    if profile is None:
        return render(request, "portal/no_profile.html")

    participations = (
        profile.participations.select_related("campaign").order_by("-invited_at")
    )
    earned = sum(
        (p.agreed_fee for p in participations if p.status == p.Status.PAID),
        start=0,
    )
    context = {
        "profile": profile,
        "participations": participations,
        "earned": earned,
        "accounts": profile.social_accounts.all(),
    }
    return render(request, "portal/home.html", context)
