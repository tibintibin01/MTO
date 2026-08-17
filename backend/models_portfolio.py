# -*- coding: utf-8 -*-
"""Organizational property portfolios.

These tables only group existing Property rows. They intentionally contain no
billing, payment, assessment, or document-computation fields.
"""

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import relationship

from backend.database import Base


class PropertyPortfolio(Base):
    __tablename__ = "property_portfolios"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False, unique=True)
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    created_by = Column(String(150), nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.current_timestamp())
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )

    links = relationship(
        "PropertyPortfolioLink",
        back_populates="portfolio",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        Index("ix_property_portfolios_active_name", "is_active", "name"),
    )


class PropertyPortfolioLink(Base):
    __tablename__ = "property_portfolio_links"

    id = Column(Integer, primary_key=True)
    portfolio_id = Column(
        Integer,
        ForeignKey("property_portfolios.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    property_id = Column(
        Integer,
        ForeignKey("properties.id", ondelete="RESTRICT"),
        nullable=False,
    )
    linked_by = Column(String(150), nullable=False)
    linked_at = Column(DateTime, nullable=False, server_default=func.current_timestamp())

    portfolio = relationship("PropertyPortfolio", back_populates="links")
    property = relationship("Property")

    __table_args__ = (
        UniqueConstraint(
            "property_id",
            name="uq_property_portfolio_links_property_id",
        ),
        Index(
            "ix_property_portfolio_links_portfolio_property",
            "portfolio_id",
            "property_id",
            unique=True,
        ),
    )
