"""Flask sample application."""

from flask import Flask

from blueprints.users import users_bp

app = Flask(__name__)

app.register_blueprint(users_bp)


@app.route("/health")
def health():
    """Health check endpoint."""
    return {"status": "ok"}


@app.route("/")
def index():
    """Root endpoint."""
    return {"message": "Welcome"}
