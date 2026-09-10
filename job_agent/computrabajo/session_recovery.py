from __future__ import annotations

from pathlib import Path
from typing import Any

from browser_use import Browser

from job_agent.computrabajo.browser_config import allowed_domains


DEFAULT_PROFILE_DIR = Path("data/browser-profile")
COMPUTRABAJO_SITE_ORIGINS: tuple[str, ...] = (
    "https://co.computrabajo.com",
    "https://secure.computrabajo.com",
    "https://candidato.co.computrabajo.com",
)


async def reset_computrabajo_site_data(profile_dir: Path | str = DEFAULT_PROFILE_DIR) -> dict[str, object]:
    """Clear only Computrabajo site state from the persistent automation profile.

    This is an explicit recovery action for broken redirect/session state. It does
    not touch Google data, saved Job Agent credentials, or unrelated browser sites.
    The next Computrabajo application may require login again.
    """

    profile_path = Path(profile_dir)
    profile_path.mkdir(parents=True, exist_ok=True)
    browser = Browser(
        user_data_dir=str(profile_path.resolve()),
        headless=False,
        allowed_domains=allowed_domains(),
        enable_default_extensions=False,
    )
    cleared: list[str] = []
    try:
        await browser.start()
        cdp = await browser.get_or_create_cdp_session(browser.agent_focus_target_id, focus=True)
        await cdp.cdp_client.send.Network.enable(session_id=cdp.session_id)
        await cdp.cdp_client.send.Storage.enable(session_id=cdp.session_id)

        # Browser cache is shared by the profile, but contains no authentication
        # credentials. Authentication/storage is cleared only for Computrabajo origins.
        await cdp.cdp_client.send.Network.clearBrowserCache(session_id=cdp.session_id)
        for origin in COMPUTRABAJO_SITE_ORIGINS:
            await cdp.cdp_client.send.Storage.clearDataForOrigin(
                params={"origin": origin, "storageTypes": "all"},
                session_id=cdp.session_id,
            )
            cleared.append(origin)

        await cdp.cdp_client.send.Page.navigate(
            params={"url": "https://co.computrabajo.com/"},
            session_id=cdp.session_id,
        )
        return {
            "ok": True,
            "cleared_origins": cleared,
            "message": "Sesión/caché de Computrabajo reparada. Puede ser necesario iniciar sesión de nuevo.",
        }
    finally:
        await browser.stop()
