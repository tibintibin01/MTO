# -*- coding: utf-8 -*-
"""Thin desktop client for organizational property portfolios."""

from api_clients.api_helper import api_request


def list_portfolios(search="", include_inactive=False):
    return api_request(
        "GET",
        "/portfolios",
        params={
            "search": str(search or "").strip(),
            "include_inactive": bool(include_inactive),
        },
        queue_offline=False,
    )


def get_portfolio(portfolio_id):
    return api_request(
        "GET",
        f"/portfolios/{int(portfolio_id)}",
        queue_offline=False,
    )


def create_portfolio(name):
    return api_request(
        "POST",
        "/portfolios",
        data={"name": str(name or "").strip()},
        queue_offline=False,
    )


def update_portfolio(portfolio_id, *, name=None, is_active=None):
    data = {}
    if name is not None:
        data["name"] = str(name).strip()
    if is_active is not None:
        data["is_active"] = bool(is_active)
    return api_request(
        "PATCH",
        f"/portfolios/{int(portfolio_id)}",
        data=data,
        queue_offline=False,
    )


def link_property(portfolio_id, property_id):
    return api_request(
        "POST",
        f"/portfolios/{int(portfolio_id)}/properties",
        data={"property_id": int(property_id)},
        queue_offline=False,
    )


def unlink_property(portfolio_id, property_id):
    return api_request(
        "DELETE",
        f"/portfolios/{int(portfolio_id)}/properties/{int(property_id)}",
        queue_offline=False,
    )
