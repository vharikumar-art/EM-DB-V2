import asyncio
from dataclasses import dataclass

from app.settings.service import get_integer_setting


@dataclass(frozen=True)
class EmailDomainPolicy:
    selection_window: int = 100
    selection_limit_per_domain: int = 5
    daily_send_limit_per_domain: int = 5
    unrestricted_domains: frozenset[str] = frozenset({"gmail.com"})

    def selection_limit(self, requested_limit: int) -> int | None:
        if requested_limit <= 0:
            return None
        windows = (requested_limit - 1) // self.selection_window + 1
        return windows * self.selection_limit_per_domain


DEFAULT_EMAIL_DOMAIN_POLICY = EmailDomainPolicy()


async def get_email_domain_policy() -> EmailDomainPolicy:
    selection_window, selection_limit, daily_send_limit = await asyncio.gather(
        get_integer_setting("email_domain_selection_window", 100, minimum=1),
        get_integer_setting("email_domain_selection_limit", 5),
        get_integer_setting("email_domain_daily_send_limit", 5),
    )
    return EmailDomainPolicy(
        selection_window=selection_window,
        selection_limit_per_domain=selection_limit,
        daily_send_limit_per_domain=daily_send_limit,
        unrestricted_domains=DEFAULT_EMAIL_DOMAIN_POLICY.unrestricted_domains,
    )
