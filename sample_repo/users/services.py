"""Business operations for user management."""

from django.db import transaction

from . import repository


def list_users():
    """Return the users displayed by the directory page."""
    return repository.list_users()


def get_user_detail(user_id):
    """Return one user or raise the model's DoesNotExist exception."""
    user = repository.get_user_by_id(user_id)
    if user is None:
        raise repository.User.DoesNotExist(f"User {user_id} does not exist")
    return user


def get_or_create_user_profile(user_id):
    """Return a user's profile, creating it for users without one yet."""
    user = get_user_detail(user_id)
    return repository.get_or_create_profile(user)


@transaction.atomic
def create_user_with_profile(
    *,
    username,
    password,
    email="",
    first_name="",
    last_name="",
    department="",
    bio="",
):
    """Create an authentication user and its profile as one transaction."""
    user = repository.create_user(
        username=username,
        password=password,
        email=email,
        first_name=first_name,
        last_name=last_name,
    )
    profile = repository.get_or_create_profile(user)
    repository.save_profile(profile, department=department, bio=bio)
    return user


@transaction.atomic
def update_user_profile(*, user_id, department, bio):
    """Update a user's profile, creating the profile if it is absent."""
    user = get_user_detail(user_id)
    profile = repository.get_or_create_profile(user)
    return repository.save_profile(profile, department=department, bio=bio)
