from django.contrib.auth import get_user_model
from django.test import TestCase

from users import services

User = get_user_model()


class UserServiceTests(TestCase):
    def test_create_user_with_profile(self):
        user = services.create_user_with_profile(
            username="grace",
            password="pass123",
            email="grace@example.com",
            department="Research",
            bio="Builds reliable systems.",
        )

        self.assertTrue(user.check_password("pass123"))
        self.assertEqual(user.profile.department, "Research")
        self.assertEqual(user.profile.bio, "Builds reliable systems.")

    def test_list_users_returns_users_in_username_order(self):
        User.objects.create_user(username="zoe", password="pass123")
        User.objects.create_user(username="amy", password="pass123")

        self.assertEqual(
            list(services.list_users().values_list("username", flat=True)),
            ["amy", "zoe"],
        )

    def test_get_user_detail_raises_for_missing_user(self):
        with self.assertRaises(User.DoesNotExist):
            services.get_user_detail(999)

    def test_update_profile_creates_a_missing_profile(self):
        user = User.objects.create_user(username="linus", password="pass123")

        profile = services.update_user_profile(
            user_id=user.pk,
            department="Platform",
            bio="Maintains shared services.",
        )

        self.assertEqual(profile.user, user)
        self.assertEqual(profile.department, "Platform")
