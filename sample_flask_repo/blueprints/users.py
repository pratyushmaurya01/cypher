"""User blueprint for Flask sample app."""

from flask import Blueprint

users_bp = Blueprint("users", __name__, url_prefix="/users")


@users_bp.route("/")
def list_users():
    """Return all users."""
    return []


@users_bp.route("/<int:user_id>", methods=["GET", "PUT"])
def user_detail(user_id):
    """Return or update a user."""
    return {}


@users_bp.route("/", methods=["POST"])
def create_user():
    """Create a new user."""
    return {}


@users_bp.route("/<int:user_id>", methods=["DELETE"])
def delete_user(user_id):
    """Delete a user."""
    return {}
