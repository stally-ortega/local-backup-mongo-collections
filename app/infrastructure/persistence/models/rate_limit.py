"""Rate-limit ORM model for throttling per-user actions."""

from datetime import datetime

from sqlalchemy import BigInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.persistence.database import Base


class RateLimitORM(Base):
    """Tracks action counts inside a sliding time window per user."""

    __tablename__ = "rate_limits"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )
    action: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    window_start: Mapped[datetime] = mapped_column(
        nullable=False,
        comment="Start of the current rate-limit window",
    )
    count: Mapped[int] = mapped_column(
        default=1,
        nullable=False,
    )
