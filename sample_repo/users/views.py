"""HTTP views for the user directory and profile management."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import redirect, render

from . import services
from .forms import ProfileUpdateForm, UserCreateForm
from .repository import User


@login_required
def user_list(request):
    users = services.list_users()
    return render(request, "users/user_list.html", {"users": users})


@login_required
def user_detail(request, user_id):
    try:
        user = services.get_user_detail(user_id)
    except User.DoesNotExist as exc:
        raise Http404("User not found") from exc
    return render(request, "users/user_detail.html", {"profile_user": user})


@login_required
def user_create(request):
    if request.method == "POST":
        form = UserCreateForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            user = services.create_user_with_profile(
                username=data["username"],
                password=data["password1"],
                email=data["email"],
                first_name=data["first_name"],
                last_name=data["last_name"],
                department=data["department"],
                bio=data["bio"],
            )
            messages.success(request, f"User {user.username} was created.")
            return redirect("users:user_detail", user_id=user.pk)
    else:
        form = UserCreateForm()

    return render(request, "users/user_form.html", {"form": form, "title": "Create user"})


@login_required
def profile_update(request, user_id):
    try:
        profile = services.get_or_create_user_profile(user_id)
    except User.DoesNotExist as exc:
        raise Http404("User not found") from exc
    profile_user = profile.user

    if request.method == "POST":
        form = ProfileUpdateForm(request.POST, instance=profile)
        if form.is_valid():
            services.update_user_profile(
                user_id=user_id,
                department=form.cleaned_data["department"],
                bio=form.cleaned_data["bio"],
            )
            messages.success(request, "Profile updated.")
            return redirect("users:user_detail", user_id=user_id)
    else:
        form = ProfileUpdateForm(instance=profile)

    return render(
        request,
        "users/user_form.html",
        {"form": form, "title": f"Update {profile_user.username}'s profile"},
    )
