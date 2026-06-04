# -*- coding: utf-8 -*-
# Client-side Property Service (Thin Client)
from api_clients.api_helper import api_request, api_request_with_cache


def search_properties(
    term, limit=50, cursor=None, kind=None, year_start=None, year_end=None, as_of_year=None, barangay=None
):
    params = {"search": term, "limit": limit}
    if cursor:
        params["cursor"] = cursor
    if kind:
        params["kind"] = kind
    if year_start:
        params["year_start"] = year_start
    if year_end:
        params["year_end"] = year_end
    if as_of_year:
        params["as_of_year"] = as_of_year
    if barangay:
        params["barangay"] = barangay
    return api_request_with_cache("GET", "/properties", params=params)


def get_barangays():
    return api_request_with_cache("GET", "/properties/barangays")


def get_property_by_id(property_id):
    return api_request_with_cache("GET", f"/properties/{property_id}")


# Placeholder for other methods that will be migrated later
def find_property_by_td_number(td_number, exclude_id=None):
    # This might need a specific endpoint
    response = api_request_with_cache("GET", "/properties", params={"search": td_number})
    results = response.get("items", [])
    for r in results:
        if str(r[1]).strip() == str(td_number).strip():
            return {"id": r[0], "td_number": r[1], "owner_name": r[2]}
    return None


def acquire_property_lock(property_id, user_name, stale_minutes=30):
    # For now, return success to keep UI working until we implement locks in API
    return {"ok": True, "locked_by": user_name}


def release_property_lock(property_id, user_name):
    pass


def release_all_property_locks(user_name):
    pass


def save_property(data, editing_id=None, idempotency_key=None, **kwargs):
    """
    Saves or updates a property record.

    Pass idempotency_key (a UUID string) when the save includes payment data
    (OR Number is set). This prevents duplicate payments from double-clicks
    or network retries — the server returns the cached response if the same
    key arrives again within 24 hours.

    Generate the key when the payment form is OPENED, not when Submit is
    clicked. This way every submission attempt uses the same key until the
    form is closed and reopened.
    """
    if editing_id:
        return api_request(
            "PUT", f"/properties/{editing_id}",
            data=data,
            idempotency_key=idempotency_key,
        )
    else:
        return api_request(
            "POST", "/properties",
            data=data,
            idempotency_key=idempotency_key,
        )


def get_assessment_roll():
    return api_request_with_cache("GET", "/billing/assessment-roll")


def get_delinquent_accounts():
    return api_request_with_cache("GET", "/properties/delinquent")


def get_receivables_by_barangay(year=None):
    params = {}
    if year:
        params["year"] = year
    return api_request_with_cache("GET", "/reports/receivables-by-barangay", params=params if params else None)


def get_deleted_properties():
    # Must NOT use cache — the list changes every time a property is deleted
    # or restored. A stale cache would hide newly deleted properties.
    result = api_request("GET", "/properties/deleted")
    if isinstance(result, dict) and "items" in result:
        return result["items"]
    return result if isinstance(result, list) else []


def restore_property(property_id, **kwargs):
    return api_request("POST", f"/properties/{property_id}/restore")


def purge_property(property_id, **kwargs):
    return api_request("DELETE", f"/properties/{property_id}/purge")


def get_unspecified_properties():
    return api_request_with_cache("GET", "/properties/unspecified")


def bulk_update_barangay(ids, barangay):
    return api_request(
        "POST",
        "/properties/bulk-update-barangay",
        data={"ids": ids, "barangay": barangay},
    )


def delete_property(property_id, **kwargs):
    return api_request("DELETE", f"/properties/{property_id}")
