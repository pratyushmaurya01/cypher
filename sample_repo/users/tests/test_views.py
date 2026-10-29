from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from users.models import Profile

User = get_user_model()


class UserViewTests(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_user(
            username="manager",
            password="pass123",
        )
        self.client.force_login(self.admin_user)
        self.profile_user = User.objects.create_user(
            username="member",
            password="pass123",
        )
        Profile.objects.create(user=self.profile_user, department="Design")

    def test_user_list_requires_authentication(self):
        self.client.logout()

        response = self.client.get(reverse("users:user_list"))

        self.assertRedirects(
            response,
            f"{reverse('login')}?next={reverse('users:user_list')}",
        )

    def test_user_list_renders_users(self):
        response = self.client.get(reverse("users:user_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "member")
        self.assertContains(response, "Design")

    def test_user_detail_renders_profile(self):
        response = self.client.get(
            reverse("users:user_detail", args=[self.profile_user.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "member")
        self.assertContains(response, "Design")

    def test_user_detail_returns_404_for_missing_user(self):
        response = self.client.get(reverse("users:user_detail", args=[999]))

        self.assertEqual(response.status_code, 404)

    def test_user_create_posts_user_and_profile(self):
        response = self.client.post(
            reverse("users:user_create"),
            {
                "username": "newmember",
                "first_name": "New",
                "last_name": "Member",
                "email": "new@example.com",
                "department": "Support",
                "bio": "Helps customers.",
                "password1": "StrongPass123!",
                "password2": "StrongPass123!",
            },
        )

        user = User.objects.get(username="newmember")
        self.assertRedirects(
            response,
            reverse("users:user_detail", args=[user.pk]),
        )
        self.assertEqual(user.profile.department, "Support")

    def test_profile_update_posts_changes(self):
        response = self.client.post(
            reverse("users:profile_update", args=[self.profile_user.pk]),
            {"department": "Product", "bio": "Designs useful tools."},
        )

        self.assertRedirects(
            response,
            reverse("users:user_detail", args=[self.profile_user.pk]),
        )
        self.profile_user.refresh_from_db()
        self.assertEqual(self.profile_user.profile.department, "Product")

    def test_profile_update_page_creates_profile_for_legacy_user(self):
        response = self.client.get(
            reverse("users:profile_update", args=[self.admin_user.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(Profile.objects.filter(user=self.admin_user).exists())
