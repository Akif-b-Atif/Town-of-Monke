"""XC-2: nothing in the adapter may call `.send(` on a channel except `send_logged` itself.
Every legitimate `.send(` (DMs, Monke Commands notices) carries an `# allow-send` marker."""
import pathlib
import re

ADAPTER = pathlib.Path(__file__).resolve().parent.parent / "monke" / "adapter"


def test_no_unmarked_channel_send():
    offenders = []
    for path in sorted(ADAPTER.glob("*.py")):
        lines = path.read_text(encoding="utf-8").splitlines()
        for n, line in enumerate(lines, 1):
            code = line.split("#", 1)[0]
            if re.search(r"\.send\(", code) and "allow-send" not in line:
                offenders.append(f"{path.name}:{n}: {line.strip()}")
    assert not offenders, "use send_logged, or mark a DM/Monke Commands send with '# allow-send':\n" + "\n".join(offenders)
