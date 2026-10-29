from django.test import SimpleTestCase
from django.urls import resolve, reverse

from users import views


class UserUrlTests(SimpleTestCase):
    def test_user_routes_resolve_to_views(self):
        cases = [
            ("users:user_list", [], views.user_list),
            ("users:user_create", [], views.user_create),
            ("users:user_detail", [7], views.user_detail),
            ("users:profile_update", [7], views.profile_update),
        ]

        for route_name, args, expected_view in cases:
            with self.subTest(route_name=route_name):
                self.assertIs(resolve(reverse(route_name, args=args)).func, expected_view)
