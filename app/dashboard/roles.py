def is_admin_dashboard_role(role: str | None) -> bool:
    return role in {"admin", "super_admin"}


def is_super_admin_role(role: str | None) -> bool:
    return role == "super_admin"
