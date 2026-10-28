import re

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_bcrypt import Bcrypt
from flask_login import login_required, login_user, logout_user

from .extensions import db
from .models import User

bp = Blueprint("auth", __name__)
bcrypt = Bcrypt()

USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,30}$")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        user = db.session.scalar(db.select(User).filter_by(username=username))
        if user and bcrypt.check_password_hash(user.password, password):
            login_user(user)
            return redirect(url_for("game.index"))
        flash("Login failed. Check your username and password.", "danger")
    return render_template("login.html")


@bp.post("/register")
def register():
    username = request.form.get("username", "")
    password = request.form.get("password", "")
    if not USERNAME_RE.match(username):
        flash("Usernames are 3 to 30 letters, numbers, or underscores.", "danger")
    elif len(password) < 8:
        flash("Passwords need at least 8 characters.", "danger")
    elif db.session.scalar(db.select(User).filter_by(username=username)):
        flash("That username is taken.", "danger")
    else:
        hashed = bcrypt.generate_password_hash(password).decode("utf-8")
        db.session.add(User(username=username, password=hashed))
        db.session.commit()
        flash("Account created. Log in below.", "success")
    return redirect(url_for("auth.login"))


@bp.post("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "success")
    return redirect(url_for("auth.login"))
