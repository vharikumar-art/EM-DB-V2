import asyncio
from unittest.mock import AsyncMock, patch

from app.settings.email_domain_policy import get_email_domain_policy


def test_email_domain_policy_loads_values_from_settings():
    configured_values = {
        "email_domain_selection_window": 50,
        "email_domain_selection_limit": 3,
        "email_domain_daily_send_limit": 8,
    }

    async def run():
        with patch(
            "app.settings.email_domain_policy.get_integer_setting",
            new_callable=AsyncMock,
            side_effect=lambda key, default, minimum=0: max(
                configured_values.get(key, default), minimum
            ),
        ):
            policy = await get_email_domain_policy()

        assert policy.selection_window == 50
        assert policy.selection_limit_per_domain == 3
        assert policy.daily_send_limit_per_domain == 8
        assert policy.unrestricted_domains == frozenset({"gmail.com"})
        assert policy.selection_limit(51) == 6

    asyncio.run(run())
