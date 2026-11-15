import time
from types import SimpleNamespace

from monke.adapter.admin_cog import AdminCog


def test_skip_guard():
    cog = AdminCog(bot=None)
    g = SimpleNamespace()
    assert cog._skipped_too_soon(1, g) is False
    cog._last_skip[1] = time.time()
    assert cog._skipped_too_soon(1, g) is True
    cog._last_skip[1] = time.time() - 10
    assert cog._skipped_too_soon(1, g) is False
    g.phase_started_at = time.time()
    assert cog._skipped_too_soon(1, g) is True


def test_is_admin_checks_live_roles():
    cfg = SimpleNamespace(admin_role_id=5)
    yes = SimpleNamespace(roles=[SimpleNamespace(id=1), SimpleNamespace(id=5)])
    no = SimpleNamespace(roles=[SimpleNamespace(id=1)])
    assert AdminCog._is_admin(yes, cfg) is True
    assert AdminCog._is_admin(no, cfg) is False