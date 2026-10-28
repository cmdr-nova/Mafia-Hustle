"""Entry point for production servers, e.g. `gunicorn wsgi:app`."""

from mafia_hustle import create_app

app = create_app()
