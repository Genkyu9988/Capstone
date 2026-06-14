"""
api/management/commands/create_supervisors.py
=============================================================================
Creates one SUPERVISOR login account per SupervisorGroup, so supervisors can
log into the web dashboard. Does NOT touch technicians, units, or any Excel
data -- it only adds User + UserProfile(role=SUP) and links each group's
`supervisor` field.

Username is derived from the group name (e.g. "Mehmet Aksu Group" ->
"mehmet.aksu"). Password defaults to "sup12345" (override with --password).

Idempotent: re-running updates existing accounts instead of duplicating.

Usage:
    python manage.py create_supervisors
    python manage.py create_supervisors --password mySecret
=============================================================================
"""
import unicodedata

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

from api.models import SupervisorGroup, UserProfile, UserRole


def _slug(name):
    # "Mehmet Aksu Group" -> "mehmet.aksu"
    name = name.replace("Group", "").strip()
    # strip Turkish accents for a clean ASCII username
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    parts = [p for p in name.lower().split() if p]
    return ".".join(parts) if parts else "supervisor"


class Command(BaseCommand):
    help = "Create one supervisor login account per group (web dashboard auth)."

    def add_arguments(self, parser):
        parser.add_argument("--password", type=str, default="sup12345")

    def handle(self, *args, **opts):
        password = opts["password"]
        created, updated = 0, 0

        self.stdout.write(self.style.SUCCESS("=== Creating supervisor accounts ==="))
        for g in SupervisorGroup.objects.all():
            username = _slug(g.name)

            user, user_created = User.objects.get_or_create(
                username=username,
                defaults={"first_name": g.name.replace("Group", "").strip()},
            )
            user.set_password(password)
            user.is_staff = False
            user.save()

            UserProfile.objects.update_or_create(
                user=user,
                defaults={"role": UserRole.SUP},
            )

            # link the group's supervisor (OneToOne) to this user
            g.supervisor = user
            g.save(update_fields=["supervisor"])

            if user_created:
                created += 1
            else:
                updated += 1

            self.stdout.write(
                f"  {g.name:24s} -> login: {username:18s} (password: {password})")

        self.stdout.write(self.style.SUCCESS(
            f"\nDone. {created} created, {updated} updated. "
            f"All supervisors can log in at /api/login/ with password '{password}'."))
