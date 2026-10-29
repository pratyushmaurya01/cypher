"""Database access functions for users and profiles."""

from django.contrib.auth import get_user_model

from .models import Profile

User = get_user_model()


def list_users():
    """Return users with their profile data loaded when available."""
    return User.objects.select_related("profile").order_by("username")


def get_user_by_id(user_id):
    """Find a user by primary key, or return None."""
    return list_users().filter(pk=user_id).first()


def create_user(*, username, password, email="", first_name="", last_name=""):
    """Persist a Django authentication user."""
    return User.objects.create_user(
        username=username,
        password=password,
        email=email,
        first_name=first_name,
        last_name=last_name,
    )


def get_or_create_profile(user):
    """Return the profile for a user, creating it for legacy users if needed."""
    profile, _created = Profile.objects.get_or_create(user=user)
    return profile


def save_profile(profile, *, department, bio):
    """Update profile fields and persist only the changed columns."""
    profile.department = department
    profile.bio = bio
    profile.save(update_fields=["department", "bio", "updated_at"])
    return profile
