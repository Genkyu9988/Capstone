import re
import unicodedata

from django.core.management.base import BaseCommand
from django.contrib.auth.models import User

from api.models import Technician, SupervisorGroup, UserProfile, UserRole

TECH_PASSWORD = "tech12345"
SUP_PASSWORD = "sup12345"


def ascii_slug(value):
    value = (value or "").replace(" Group", "").replace(" group", "")
    tr_map = str.maketrans({
        "ç": "c", "Ç": "c",
        "ğ": "g", "Ğ": "g",
        "ı": "i", "I": "i", "İ": "i",
        "ö": "o", "Ö": "o",
        "ş": "s", "Ş": "s",
        "ü": "u", "Ü": "u",
    })
    value = value.translate(tr_map)
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    parts = re.findall(r"[a-zA-Z0-9]+", value.lower())
    return ".".join(parts[:2]) if len(parts) >= 2 else (parts[0] if parts else "user")


def existing_t_numbers():
    nums = set()
    for username in User.objects.filter(username__regex=r"^t[0-9]+$").values_list("username", flat=True):
        m = re.match(r"^t(\d+)$", str(username).lower())
        if m:
            nums.add(int(m.group(1)))
    return nums


def next_t_username(used):
    n = max(used or {100}) + 1
    while User.objects.filter(username=f"t{n}").exists() or n in used:
        n += 1
    used.add(n)
    return f"t{n}"


class Command(BaseCommand):
    help = "Normalize demo logins: technicians t###/tech12345, supervisors first.last/sup12345."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--show", action="store_true")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        show = options["show"]

        self.stdout.write("DEMO CREDENTIAL NORMALIZATION")
        self.stdout.write("=" * 100)
        self.stdout.write(f"Technician password target: {TECH_PASSWORD}")
        self.stdout.write(f"Supervisor password target:  {SUP_PASSWORD}")
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN ONLY - no database changes will be saved."))
        self.stdout.write("")

        # Supervisors: ahmet.ylmaz / sup12345, yusuf.arslan / sup12345, etc.
        self.stdout.write("SUPERVISORS")
        self.stdout.write("-" * 100)
        for group in SupervisorGroup.objects.select_related("supervisor").order_by("name"):
            user = group.supervisor
            desired = ascii_slug(group.name)
            final_username = desired
            i = 2
            while User.objects.filter(username=final_username).exclude(pk=user.pk).exists():
                final_username = f"{desired}{i}"
                i += 1

            if show or user.username != final_username:
                self.stdout.write(f"{group.name:25} | {user.username} -> {final_username} | password -> {SUP_PASSWORD}")

            if not dry_run:
                user.username = final_username
                user.is_active = True
                user.set_password(SUP_PASSWORD)
                user.save()
                UserProfile.objects.update_or_create(user=user, defaults={"role": UserRole.SUP})

        self.stdout.write("")
        self.stdout.write("TECHNICIANS")
        self.stdout.write("-" * 100)
        used_numbers = existing_t_numbers()

        for tech in Technician.objects.select_related("user", "group").order_by("id"):
            user = tech.user
            created_user = False
            if user is None:
                username = next_t_username(used_numbers)
                user = User(username=username, first_name=(tech.full_name or "").split(" ")[0] if tech.full_name else "")
                created_user = True
            else:
                m = re.match(r"^t(\d+)$", str(user.username or "").lower())
                if m:
                    username = user.username.lower()
                    used_numbers.add(int(m.group(1)))
                else:
                    username = next_t_username(used_numbers)

            old_username = user.username
            if show or created_user or old_username != username:
                self.stdout.write(
                    f"{tech.full_name:30} | {old_username or 'NO USER'} -> {username} | password -> {TECH_PASSWORD}"
                )

            if not dry_run:
                user.username = username
                user.is_active = True
                if not user.first_name and tech.full_name:
                    parts = tech.full_name.split()
                    user.first_name = parts[0]
                    user.last_name = parts[-1] if len(parts) > 1 else ""
                user.set_password(TECH_PASSWORD)
                user.save()
                UserProfile.objects.update_or_create(user=user, defaults={"role": UserRole.TECH})
                if tech.user_id != user.id:
                    tech.user = user
                    tech.save(update_fields=["user"])

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run complete. No changes applied."))
        else:
            self.stdout.write(self.style.SUCCESS("Demo credentials normalized successfully."))
            self.stdout.write("Supervisors use sup12345. Technicians use tech12345.")
