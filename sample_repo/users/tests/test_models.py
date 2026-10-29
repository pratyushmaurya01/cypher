from django.contrib.auth import get_user_model
from django.test import TestCase

from users.models import Profile

User = get_user_model()


class ProfileModelTests(TestCase):
    def test_profile_is_related_to_user(self):
        user = User.objects.create_user(username="ada", password="pass123")
        profile = Profile.objects.create(user=user, department="Engineering")

        self.assertEqual(user.profile, profile)
        self.assertEqual(str(profile), "Profile for ada")
