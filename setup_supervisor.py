"""
setup_supervisor.py
=============================================================================
Creates/updates the supervisor account that logs into the web dashboard.
Run AFTER scenario_can_mehmet.py.

    python setup_supervisor.py

It prints the username, password, and auth token. Paste the token into
supervisor_dashboard.dart at the top (the kSupervisorToken constant).
=============================================================================
"""
import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "capstone.settings")
django.setup()

from django.contrib.auth import get_user_model
from rest_framework.authtoken.models import Token

from api.models import UserProfile, UserRole

User = get_user_model()

print("Setting up supervisor for the web dashboard...\n")

# 1) admin_test user with a real password
user, _ = User.objects.get_or_create(
    username="admin_test",
    defaults={"first_name": "Demo", "last_name": "Supervisor"},
)
user.set_password("admin12345")
user.is_staff = True
user.save()
print(f"  user:    admin_test (password set)")

# 2) UserProfile with ADMIN role so role-gated views accept this user
profile, _ = UserProfile.objects.get_or_create(
    user=user,
    defaults={"role": UserRole.ADMIN},
)
profile.role = UserRole.ADMIN
profile.save()
print(f"  profile: ADMIN")

# 3) Auth token for the dashboard
token, created = Token.objects.get_or_create(user=user)
print(f"  token:   {token.key} ({'new' if created else 'reused'})")

print()
print("=" * 70)
print("SUPERVISOR DASHBOARD LOGIN")
print("=" * 70)
print(f"  Username: admin_test")
print(f"  Password: admin12345")
print(f"  Token:    {token.key}")
print("=" * 70)
print()
print("Next: paste the token above into lib/web/supervisor_dashboard.dart")
print("at the constant `kSupervisorToken`.")