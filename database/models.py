from datetime import datetime
from enum import Enum as PyEnum
from sqlalchemy import (
    BigInteger, String, Boolean, DateTime,
    ForeignKey, Text, Integer, Enum, JSON
)
from sqlalchemy.orm import relationship, Mapped, mapped_column
from core.database import Base

class PlanType(str, PyEnum):
    TRIAL = "trial"
    VIP_1 = "vip_1"
    VIP_7 = "vip_7"
    VIP_15 = "vip_15"
    CUSTOM = "custom"

class SubscriptionStatus(str, PyEnum):
    ACTIVE = "active"
    EXPIRED = "expired"
    CANCELLED = "cancelled"

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    username: Mapped[str] = mapped_column(String(64), nullable=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    
    agreed_terms: Mapped[bool] = mapped_column(Boolean, default=False)

    # Referal tizimi
    referred_by: Mapped[int] = mapped_column(BigInteger, nullable=True)
    referral_count: Mapped[int] = mapped_column(Integer, default=0)

    has_used_trial: Mapped[bool] = mapped_column(Boolean, default=False)
    trial_started_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    session: Mapped["UserbotSession"] = relationship("UserbotSession", back_populates="user", uselist=False, cascade="all, delete-orphan")
    subscriptions: Mapped[list["Subscription"]] = relationship("Subscription", back_populates="user", cascade="all, delete-orphan")
    settings: Mapped["UserbotSettings"] = relationship("UserbotSettings", back_populates="user", uselist=False, cascade="all, delete-orphan")
    payments: Mapped[list["Payment"]] = relationship("Payment", back_populates="user")


class UserbotSession(Base):
    __tablename__ = "userbot_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    phone_number: Mapped[str] = mapped_column(String(32), nullable=True)
    encrypted_session: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    connected_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user: Mapped["User"] = relationship("User", back_populates="session")


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"))
    
    plan: Mapped[PlanType] = mapped_column(Enum(PlanType), default=PlanType.TRIAL)
    status: Mapped[SubscriptionStatus] = mapped_column(Enum(SubscriptionStatus), default=SubscriptionStatus.ACTIVE)
    
    starts_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped["User"] = relationship("User", back_populates="subscriptions")


class UserbotSettings(Base):
    __tablename__ = "userbot_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), unique=True)

    auto_comment_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    comment_text: Mapped[str] = mapped_column(Text, default="Zo'r post! 👍")
    comment_delay: Mapped[int] = mapped_column(Integer, default=5)
    target_channels: Mapped[dict] = mapped_column(JSON, default=list)

    save_destructing_media: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_stories_view: Mapped[bool] = mapped_column(Boolean, default=False)

    user: Mapped["User"] = relationship("User", back_populates="settings")


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="UZS")
    plan: Mapped[PlanType] = mapped_column(Enum(PlanType), nullable=False)
    
    telegram_charge_id: Mapped[str] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped["User"] = relationship("User", back_populates="payments")
