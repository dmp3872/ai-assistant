"""ORM models. See docs/database-schema.md for intent."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Connector(Base):
    __tablename__ = "connectors"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    cursor: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="ok")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class Item(Base):
    __tablename__ = "items"
    __table_args__ = (UniqueConstraint("source", "source_id", name="uq_source_item"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(32), index=True)
    source_id: Mapped[str] = mapped_column(String(255))
    thread_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    author: Mapped[str | None] = mapped_column(String(255), nullable=True)
    author_handle: Mapped[str | None] = mapped_column(String(255), nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    body_clean: Mapped[str | None] = mapped_column(Text, nullable=True)
    body_hash: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    category: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    priority: Mapped[str | None] = mapped_column(String(16), nullable=True)
    needs_response: Mapped[bool] = mapped_column(Boolean, default=False)
    injection_flag: Mapped[bool] = mapped_column(Boolean, default=False)
    spam: Mapped[bool] = mapped_column(Boolean, default=False)
    handled: Mapped[bool] = mapped_column(Boolean, default=False)
    snoozed_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    raw_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    drafts: Mapped[list["Draft"]] = relationship(back_populates="item")


class Draft(Base):
    __tablename__ = "drafts"
    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), index=True)
    draft_text: Mapped[str] = mapped_column(Text)
    confidence: Mapped[str] = mapped_column(String(16), default="low")
    review_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    sources_used: Mapped[str | None] = mapped_column(Text, nullable=True)  # json
    model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    item: Mapped["Item"] = relationship(back_populates="drafts")


class Sale(Base):
    __tablename__ = "sales"
    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), index=True)
    vendor: Mapped[str | None] = mapped_column(String(255), nullable=True)
    promo_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    discount: Mapped[str | None] = mapped_column(String(255), nullable=True)
    stacking_rules: Mapped[str | None] = mapped_column(Text, nullable=True)
    coupon_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    start_date: Mapped[str | None] = mapped_column(String(64), nullable=True)
    end_date: Mapped[str | None] = mapped_column(String(64), nullable=True)   # display, e.g. "Jul 21"
    end_iso: Mapped[str | None] = mapped_column(String(10), nullable=True)    # sortable YYYY-MM-DD
    end_tz: Mapped[str | None] = mapped_column(String(64), nullable=True)
    exclusions: Mapped[str | None] = mapped_column(Text, nullable=True)
    free_shipping_threshold: Mapped[str | None] = mapped_column(String(128), nullable=True)
    giveaway: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[str] = mapped_column(String(16), default="low")
    contradicts_sale_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class ContentOpportunity(Base):
    __tablename__ = "content_opportunities"
    id: Mapped[int] = mapped_column(primary_key=True)
    question: Mapped[str] = mapped_column(Text)
    occurrences: Mapped[int] = mapped_column(Integer, default=1)
    sources: Mapped[str | None] = mapped_column(Text, nullable=True)  # json
    suggested_format: Mapped[str | None] = mapped_column(String(128), nullable=True)
    related_content: Mapped[str | None] = mapped_column(Text, nullable=True)  # json
    outline: Mapped[str | None] = mapped_column(Text, nullable=True)
    first_seen: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_seen: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ReviewHistory(Base):
    __tablename__ = "review_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), index=True)
    draft_id: Mapped[int | None] = mapped_column(ForeignKey("drafts.id"), nullable=True)
    final_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    edit_distance: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rejected: Mapped[bool] = mapped_column(Boolean, default=False)
    feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class DailyTask(Base):
    """A checkable item for a single day. Content quotas seed fresh each day (daily
    reset = each day has its own rows); calendar-derived to-dos can also live here."""
    __tablename__ = "daily_tasks"
    id: Mapped[int] = mapped_column(primary_key=True)
    day: Mapped[str] = mapped_column(String(10), index=True)   # YYYY-MM-DD
    kind: Mapped[str] = mapped_column(String(24))              # tiktok/skool/substack/youtube/todo
    label: Mapped[str] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer, default=0)
    scheduled_time: Mapped[str | None] = mapped_column(String(5), nullable=True)  # HH:MM
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    done: Mapped[bool] = mapped_column(Boolean, default=False)
    done_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    kind: Mapped[str] = mapped_column(String(32))
    source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)  # json
