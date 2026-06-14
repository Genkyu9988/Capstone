"""
set_tech_passwords.py
=============================================================================
Sets ONE known password for every technician in the Ahmet Yılmaz Group so you
can log into the mobile app as any of them for testing.

Usernames already exist in the DB (t081..t121); this only sets their password
(properly hashed by Django -- never write raw passwords into sqlite directly).

Place this file in the project root (next to manage.py) and run:

    python set_tech_passwords.py
=============================================================================
"""
import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "capstone.settings")
django.setup()

from api.models import Technician  # noqa: E402

PASSWORD = "test1234"
GROUP_MATCH = "Ahmet"

techs = (
    Technician.objects
    .filter(group__name__icontains=GROUP_MATCH, user__isnull=False)
    .select_related("user")
    .order_by("user__username")
)

print(f"Setting password '{PASSWORD}' for technicians in the {GROUP_MATCH} group:\n")
count = 0
for t in techs:
    u = t.user
    u.set_password(PASSWORD)
    u.save(update_fields=["password"])
    print(f"  {u.username:8s} | {t.full_name}")
    count += 1

print(f"\nDone. {count} technicians can now log in with password: {PASSWORD}")
print("Mobile test example -> username: t084  (Can Şahindaş)   password: test1234")
