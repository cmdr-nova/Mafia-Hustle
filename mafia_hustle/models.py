from flask_login import UserMixin
from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .extensions import db


class User(db.Model, UserMixin):
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True)
    password: Mapped[str] = mapped_column(String(200))
    health: Mapped[int] = mapped_column(default=100)
    money: Mapped[int] = mapped_column(default=1000)
    level: Mapped[int] = mapped_column(default=1)
    points: Mapped[int] = mapped_column(default=0)
    kills: Mapped[int] = mapped_column(default=0)
    prestige: Mapped[int] = mapped_column(default=0)
    avatar_url: Mapped[str | None] = mapped_column(String(500))
