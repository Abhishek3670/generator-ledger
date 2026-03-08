"""
Permission capability definitions and resolution helpers.
"""

from typing import Dict, Mapping

from config import ROLE_ADMIN, ROLE_OPERATOR

CAPABILITY_SETTINGS_USER_ADMIN = "settings_user_admin"
CAPABILITY_MONITOR_ACCESS = "monitor_access"
CAPABILITY_VENDOR_MANAGEMENT = "vendor_management"
CAPABILITY_GENERATOR_MANAGEMENT = "generator_management"
CAPABILITY_BOOKING_CREATE_UPDATE = "booking_create_update"
CAPABILITY_BOOKING_DELETE = "booking_delete"
CAPABILITY_BILLING_ACCESS = "billing_access"
CAPABILITY_EXPORT_ACCESS = "export_access"
CAPABILITY_READ_ONLY_OPERATIONAL_VIEWS = "read_only_operational_views"

PERMISSION_MATRIX_CAPABILITIES = (
    {
        "key": CAPABILITY_SETTINGS_USER_ADMIN,
        "label": "Settings & User Admin",
        "description": "Access settings and manage user accounts.",
        "endpoint_refs": (
            "GET /admin/settings",
            "POST /admin/settings/users/create",
            "POST /admin/settings/users/{user_id}/update",
            "POST /admin/settings/users/{user_id}/password",
            "POST /admin/settings/users/{user_id}/delete",
            "POST /admin/settings/users/{user_id}/permissions",
        ),
        "admin_allowed": True,
        "operator_allowed": False,
        "editable": False,
    },
    {
        "key": CAPABILITY_MONITOR_ACCESS,
        "label": "Monitor",
        "description": "View live monitor metrics and health checks.",
        "endpoint_refs": (
            "GET /api/monitor/live",
            "GET /health",
            "GET /api/info",
        ),
        "admin_allowed": True,
        "operator_allowed": False,
        "editable": True,
    },
    {
        "key": CAPABILITY_VENDOR_MANAGEMENT,
        "label": "Vendor Management",
        "description": "Create, update, and delete retailer and rental vendors.",
        "endpoint_refs": (
            "POST /api/vendors",
            "PATCH /api/vendors/{vendor_id}",
            "DELETE /api/vendors/{vendor_id}",
            "POST /api/rental-vendors",
            "PATCH /api/rental-vendors/{vendor_id}",
            "DELETE /api/rental-vendors/{vendor_id}",
        ),
        "admin_allowed": True,
        "operator_allowed": False,
        "editable": True,
    },
    {
        "key": CAPABILITY_GENERATOR_MANAGEMENT,
        "label": "Generator Management",
        "description": "Create generator records.",
        "endpoint_refs": (
            "POST /api/generators",
        ),
        "admin_allowed": True,
        "operator_allowed": False,
        "editable": True,
    },
    {
        "key": CAPABILITY_BOOKING_CREATE_UPDATE,
        "label": "Booking Create/Update",
        "description": "Create bookings and manage booking items.",
        "endpoint_refs": (
            "POST /api/bookings",
            "POST /api/bookings/{booking_id}/items",
            "POST /api/bookings/{booking_id}/items/bulk-update",
            "POST /api/bookings/{booking_id}/cancel",
        ),
        "admin_allowed": True,
        "operator_allowed": True,
        "editable": True,
    },
    {
        "key": CAPABILITY_BOOKING_DELETE,
        "label": "Booking Delete",
        "description": "Delete existing bookings.",
        "endpoint_refs": (
            "DELETE /api/bookings/{booking_id}",
        ),
        "admin_allowed": True,
        "operator_allowed": False,
        "editable": True,
    },
    {
        "key": CAPABILITY_BILLING_ACCESS,
        "label": "Billing Access",
        "description": "Access billing pages and billing line APIs.",
        "endpoint_refs": (
            "GET /billing",
            "GET /api/billing/lines",
        ),
        "admin_allowed": True,
        "operator_allowed": False,
        "editable": True,
    },
    {
        "key": CAPABILITY_EXPORT_ACCESS,
        "label": "Export",
        "description": "Export data via API.",
        "endpoint_refs": (
            "GET /api/export",
        ),
        "admin_allowed": True,
        "operator_allowed": False,
        "editable": True,
    },
    {
        "key": CAPABILITY_READ_ONLY_OPERATIONAL_VIEWS,
        "label": "Read-only Operational Views",
        "description": "View operational pages and read APIs.",
        "endpoint_refs": (
            "GET /",
            "GET /bookings",
            "GET /history",
            "GET /vendors",
            "GET /generators",
            "GET /create-booking",
            "GET /booking/{booking_id}",
            "GET /booking/{booking_id}/edit",
            "GET /api/bookings",
            "GET /api/bookings/{booking_id}",
            "GET /api/vendors",
            "GET /api/vendors/{vendor_id}/bookings",
            "GET /api/rental-vendors",
            "GET /api/generators",
            "GET /api/generators/{generator_id}/bookings",
            "GET /api/calendar/events",
            "GET /api/calendar/day",
        ),
        "admin_allowed": True,
        "operator_allowed": True,
        "editable": True,
    },
)

ALL_CAPABILITY_KEYS = tuple(row["key"] for row in PERMISSION_MATRIX_CAPABILITIES)
EDITABLE_CAPABILITY_KEYS = tuple(
    row["key"] for row in PERMISSION_MATRIX_CAPABILITIES if row.get("editable", True)
)

ROLE_DEFAULT_CAPABILITIES = {
    ROLE_ADMIN: {row["key"]: bool(row["admin_allowed"]) for row in PERMISSION_MATRIX_CAPABILITIES},
    ROLE_OPERATOR: {
        row["key"]: bool(row["operator_allowed"]) for row in PERMISSION_MATRIX_CAPABILITIES
    },
}


def normalize_role(role: str) -> str:
    return (role or "").strip().lower()


def role_default_permissions(role: str) -> Dict[str, bool]:
    normalized_role = normalize_role(role)
    defaults = ROLE_DEFAULT_CAPABILITIES.get(normalized_role, {})
    return {
        capability_key: bool(defaults.get(capability_key, False))
        for capability_key in ALL_CAPABILITY_KEYS
    }


def normalize_permission_overrides(
    overrides: Mapping[str, bool] | None,
) -> Dict[str, bool]:
    if not overrides:
        return {}
    normalized: Dict[str, bool] = {}
    for capability_key, is_allowed in overrides.items():
        if capability_key not in EDITABLE_CAPABILITY_KEYS:
            continue
        normalized[str(capability_key)] = bool(is_allowed)
    return normalized


def resolve_configured_permissions(
    role: str,
    overrides: Mapping[str, bool] | None = None,
) -> Dict[str, bool]:
    defaults = role_default_permissions(role)
    configured = dict(defaults)
    configured.update(normalize_permission_overrides(overrides))
    configured[CAPABILITY_SETTINGS_USER_ADMIN] = defaults.get(
        CAPABILITY_SETTINGS_USER_ADMIN,
        False,
    )
    return configured


def resolve_effective_permissions(
    role: str,
    is_active: bool,
    overrides: Mapping[str, bool] | None = None,
) -> Dict[str, bool]:
    configured = resolve_configured_permissions(role, overrides)
    if is_active:
        return configured
    return {
        capability_key: False
        for capability_key in ALL_CAPABILITY_KEYS
    }
