from pathlib import Path
from types import SimpleNamespace

import pytest

from job_agent.computrabajo.deterministic_application import DeterministicApplicationRunner
import job_agent.computrabajo.session_recovery as recovery_module


def test_one_click_application_confirmations_are_detected_without_ai() -> None:
    assert DeterministicApplicationRunner._submission_confirmation("Te aplicaste correctamente") == "submitted"
    assert DeterministicApplicationRunner._submission_confirmation("Ya aplicaste a esta oferta") == "already_applied"


@pytest.mark.asyncio
async def test_session_recovery_clears_site_data_without_storage_enable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, object]] = []

    async def network_enable(*, session_id: str) -> None:
        calls.append(("Network.enable", session_id))

    async def clear_cache(*, session_id: str) -> None:
        calls.append(("Network.clearBrowserCache", session_id))

    async def clear_origin(*, params: dict[str, str], session_id: str) -> None:
        calls.append(("Storage.clearDataForOrigin", params["origin"]))

    async def navigate(*, params: dict[str, str], session_id: str) -> None:
        calls.append(("Page.navigate", params["url"]))

    fake_cdp = SimpleNamespace(
        session_id="session-1",
        cdp_client=SimpleNamespace(
            send=SimpleNamespace(
                Network=SimpleNamespace(enable=network_enable, clearBrowserCache=clear_cache),
                Storage=SimpleNamespace(clearDataForOrigin=clear_origin),
                Page=SimpleNamespace(navigate=navigate),
            )
        ),
    )

    class FakeBrowser:
        agent_focus_target_id = "target-1"

        def __init__(self, **_: object) -> None:
            pass

        async def start(self) -> None:
            return None

        async def get_or_create_cdp_session(self, *_: object, **__: object):
            return fake_cdp

        async def stop(self) -> None:
            calls.append(("Browser.stop", True))

    monkeypatch.setattr(recovery_module, "Browser", FakeBrowser)

    result = await recovery_module.reset_computrabajo_site_data(tmp_path / "browser")

    assert result["ok"] is True
    cleared = [value for name, value in calls if name == "Storage.clearDataForOrigin"]
    assert cleared == list(recovery_module.COMPUTRABAJO_SITE_ORIGINS)
    assert ("Network.clearBrowserCache", "session-1") in calls
    assert ("Page.navigate", "https://co.computrabajo.com/") in calls
