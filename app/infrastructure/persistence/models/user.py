"""User ORM model for whitelist and RBAC."""

from datetime import datetime

from sqlalchemy import BigInteger, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.persistence.database import Base


class UserORM(Base):
    """Represents an authorised Telegram user and their role."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(
        BigInteger,
        unique=True,
        nullable=False,
        comment="Telegram user ID; enforced unique to prevent duplicate whitelisting",
    )
    username: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="RBAC role: ADMIN, DBA, OPERATOR, READONLY",
    )
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
