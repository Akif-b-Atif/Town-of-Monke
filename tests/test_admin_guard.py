import time
from types import SimpleNamespace

from monke.adapter import handlers


def test_skip_guard_measures_from_the_phase_change():
    g = SimpleNamespace()
    handlers._last_skip.clear()
    assert handlers._skipped_too_soon(1, g) is False
    handlers._last_skip[1] = time.time()
    assert handlers._skipped_too_soon(1, g) is True
    handlers._last_skip[1] = time.time() - 10
    assert handlers._skipped_too_soon(1, g) is False
    g.phase_started_at = time.time()  # FIX-4: the phase just changed
    assert handlers._skipped_too_soon(1, g) is True
    g.phase_started_at = time.time() - 60
    assert handlers._skipped_too_soon(1, g) is False
    handlers._last_skip.clear()
