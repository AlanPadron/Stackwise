"""External identity providers linked to a local account.

One row per (provider, provider_user_id). The access token is kept because
GitHub is also the source of the repositories the user imports — it is the
credential used by `app/services/github.py`.

Kept in its own table rather than as columns on `users` so linking several
providers to one account stays a plain insert, and `users` needs no migration.
"""

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.base import Base


class OAuthAccount(Base):
    __tablename__ = "oauth_accounts"
    __table_args__ = (
        UniqueConstraint("provider", "provider_user_id", name="uq_oauth_provider_user"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider = Column(String, nullable=False)  # google | github
    provider_user_id = Column(String, nullable=False)  # the provider's own id for the account
    provider_login = Column(String, nullable=True)  # GitHub login, for "connected as @user"
    email = Column(String, nullable=True)  # email the provider reported
    access_token = Column(Text, nullable=True)  # provider token; used to call its API
    scope = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="oauth_accounts")
