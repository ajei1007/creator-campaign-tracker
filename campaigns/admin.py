from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.db.models import Count, Sum
from django.utils import timezone
from django.utils.html import format_html

from .models import Campaign, Creator, Participation, SocialAccount


class SocialAccountInline(admin.TabularInline):
    model = SocialAccount
    extra = 1
    fields = ("platform", "handle", "followers", "avg_views", "engagement_rate_display", "verified")
    readonly_fields = ("engagement_rate_display",)

    @admin.display(description="Engagement")
    def engagement_rate_display(self, obj):
        if obj.pk:
            return f"{obj.engagement_rate}%"
        return "—"


class ParticipationInline(admin.TabularInline):
    model = Participation
    extra = 0
    fields = ("creator", "status", "agreed_fee", "content_url", "submitted_at", "paid_at")
    readonly_fields = ("submitted_at", "paid_at")
    autocomplete_fields = ("creator",)


@admin.register(Creator)
class CreatorAdmin(admin.ModelAdmin):
    list_display = ("display_name", "niche", "country", "total_followers_display", "active_campaign_count", "avatar_tag")
    list_filter = ("niche", "country")
    search_fields = ("display_name", "email", "social_accounts__handle")
    inlines = [SocialAccountInline]
    readonly_fields = ("avatar_tag", "created_at")
    autocomplete_fields = ("portal_user",)

    @admin.display(description="Followers", ordering="display_name")
    def total_followers_display(self, obj):
        return f"{obj.total_followers:,}"

    @admin.display(description="Avatar")
    def avatar_tag(self, obj):
        if obj.avatar:
            return format_html('<img src="{}" style="height:40px;border-radius:50%;" />', obj.avatar.url)
        return "—"


@admin.register(SocialAccount)
class SocialAccountAdmin(admin.ModelAdmin):
    list_display = ("handle", "platform", "creator", "followers", "engagement_rate_display", "verified")
    list_filter = ("platform", "verified")
    search_fields = ("handle", "creator__display_name")
    autocomplete_fields = ("creator",)

    @admin.display(description="Engagement rate")
    def engagement_rate_display(self, obj):
        return f"{obj.engagement_rate}%"


@admin.register(Campaign)
class CampaignAdmin(admin.ModelAdmin):
    list_display = (
        "name", "brand", "status", "budget", "committed_display",
        "budget_remaining_display", "participants_display", "end_date",
    )
    list_filter = ("status", "brand", "start_date")
    search_fields = ("name", "brand", "description")
    date_hierarchy = "start_date"
    inlines = [ParticipationInline]
    readonly_fields = ("banner_tag", "committed_display", "budget_remaining_display", "created_at")
    fieldsets = (
        (None, {"fields": ("name", "brand", "status", "description")}),
        ("Budget & capacity", {"fields": ("budget", "max_creators", "committed_display", "budget_remaining_display")}),
        ("Schedule", {"fields": ("start_date", "end_date")}),
        ("Media", {"fields": ("banner", "banner_tag")}),
        ("Meta", {"fields": ("created_at",)}),
    )
    actions = ["activate_campaigns", "mark_completed"]

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.annotate(_pcount=Count("participations"))

    @admin.display(description="Committed")
    def committed_display(self, obj):
        return f"${obj.committed_spend:,.0f}"

    @admin.display(description="Remaining")
    def budget_remaining_display(self, obj):
        remaining = obj.budget_remaining
        color = "#b91c1c" if remaining < 0 else "#166534"
        return format_html('<b style="color:{}">${}</b>', color, f"{remaining:,.0f}")

    @admin.display(description="Creators")
    def participants_display(self, obj):
        return f"{obj.active_participant_count}/{obj.max_creators}"

    @admin.display(description="Banner")
    def banner_tag(self, obj):
        if obj.banner:
            return format_html('<img src="{}" style="max-height:120px;" />', obj.banner.url)
        return "—"

    @admin.action(description="Activate selected draft campaigns")
    def activate_campaigns(self, request, queryset):
        updated = queryset.filter(status=Campaign.Status.DRAFT).update(status=Campaign.Status.ACTIVE)
        self.message_user(request, f"{updated} campaign(s) activated.", messages.SUCCESS)

    @admin.action(description="Mark selected campaigns completed")
    def mark_completed(self, request, queryset):
        blocked, done = [], 0
        for campaign in queryset:
            unpaid = campaign.participations.filter(
                status__in=[Participation.Status.APPROVED, Participation.Status.SUBMITTED]
            ).exists()
            if unpaid:
                blocked.append(campaign.name)
                continue
            campaign.status = Campaign.Status.COMPLETED
            campaign.save(update_fields=["status"])
            done += 1
        if done:
            self.message_user(request, f"{done} campaign(s) marked completed.", messages.SUCCESS)
        if blocked:
            self.message_user(
                request,
                "Not completed (approved content still unpaid): " + ", ".join(blocked),
                messages.WARNING,
            )

    # Reviewers get a read-only campaign view; only managers/admins edit.
    def has_add_permission(self, request):
        return request.user.is_superuser or request.user.is_manager

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser or request.user.is_manager

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    def get_actions(self, request):
        actions = super().get_actions(request)
        if not (request.user.is_superuser or request.user.is_manager):
            actions.pop("activate_campaigns", None)
            actions.pop("mark_completed", None)
        return actions


@admin.register(Participation)
class ParticipationAdmin(admin.ModelAdmin):
    list_display = ("creator", "campaign", "status", "agreed_fee", "submitted_at", "paid_at")
    list_filter = ("status", "campaign__brand", "campaign")
    search_fields = ("creator__display_name", "campaign__name")
    autocomplete_fields = ("creator", "campaign")
    readonly_fields = ("submitted_at", "approved_at", "paid_at", "invited_at")
    actions = ["approve_submissions", "mark_paid"]

    @admin.action(description="Approve selected submitted content")
    def approve_submissions(self, request, queryset):
        done, blocked = 0, 0
        for p in queryset:
            if p.status == Participation.Status.SUBMITTED:
                p.status = Participation.Status.APPROVED
                try:
                    p.full_clean(exclude=["creator", "campaign"])
                    p.save()
                    done += 1
                except ValidationError:
                    blocked += 1
            else:
                blocked += 1
        self.message_user(request, f"{done} approved, {blocked} skipped (not in a submittable state).", messages.INFO)

    @admin.action(description="Mark approved content as paid")
    def mark_paid(self, request, queryset):
        if not request.user.can_manage_payments:
            self.message_user(request, "You do not have permission to pay creators.", messages.ERROR)
            return
        done, blocked = 0, 0
        for p in queryset:
            if p.status == Participation.Status.APPROVED and p.agreed_fee > 0:
                p.status = Participation.Status.PAID
                p.save()
                done += 1
            else:
                blocked += 1
        self.message_user(request, f"{done} marked paid, {blocked} skipped.", messages.INFO)

    def get_readonly_fields(self, request, obj=None):
        ro = list(super().get_readonly_fields(request, obj))
        # Reviewers may triage up to approval but never touch money or payment state.
        if not request.user.can_manage_payments:
            ro += ["agreed_fee"]
        return ro

    def formfield_for_choice_field(self, db_field, request, **kwargs):
        # Reviewers triage bookings but can't pay: drop "Paid" from the choices
        # they can pick so the edit form can't do what the action won't.
        if db_field.name == "status" and not request.user.can_manage_payments:
            kwargs["choices"] = [
                c for c in Participation.Status.choices if c[0] != Participation.Status.PAID
            ]
        return super().formfield_for_choice_field(db_field, request, **kwargs)

    def has_add_permission(self, request):
        return request.user.is_superuser or request.user.is_manager

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    def get_actions(self, request):
        actions = super().get_actions(request)
        if not request.user.can_manage_payments:
            actions.pop("mark_paid", None)
        return actions


admin.site.site_header = "Creator Campaign Admin"
admin.site.site_title = "Creator Campaign Admin"
admin.site.index_title = "Campaign operations"
