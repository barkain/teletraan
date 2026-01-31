"""User settings model for storing application preferences."""

from datetime import datetime

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class UserSettings(Base):
    """Model representing user settings/preferences stored as key-value pairs."""

    __tablename__ = "user_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    value: Mapped[str] = mapped_column(Text)  # JSON serialized value
    updated_at: Mapped[datetime] = mapped_column(
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    def __repr__(self) -> str:
        return f"<UserSettings(key={self.key!r})>"
