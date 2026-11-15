"""The flavour text bank (TXT-1 to TXT-3).

All player-visible text lives in one editable YAML file. The engine contains no prose: its events carry a
`text_key` and variables, and only the renderer resolves them here.

* A value is one string or a list of variants. A shuffle bag per (game, key) draws variants without replacement and
  never repeats the last draw first. It has its own RNG, separate from the game RNG, so replays are unaffected.
* `load_text()` validates a file against the registry (keys.py) and reports every problem with its key and line.
* A missing key or variable at runtime never crashes a game: the shipped default (or a '?') is used."""
from __future__ import annotations

import logging
import pathlib
import random
import string
from dataclasses import dataclass, field
from typing import Callable, Optional

import yaml

from .keys import TEXT_KEYS, KeySpec

log = logging.getLogger("monke.text")

DEFAULT_PATH = pathlib.Path(__file__).resolve().parent.parent / "data" / "flavour_default.yaml"
SLOT_VARS = ("player", "target", "previous", "actor")  # ints in vars are slots; the renderer names them (NAM-2)


class TextError(Exception):
    """Raised by a strict bank (tests, the simulator) for a missing key or variable."""


@dataclass
class Problem:
    key: str
    line: int
    message: str

    def __str__(self) -> str:
        where = f"line {self.line}: " if self.line else ""
        return f"{where}`{self.key}`: {self.message}" if self.key else f"{where}{self.message}"


@dataclass
class Report:
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    keys: int = 0

    @property
    def ok(self) -> bool:
        return not self.errors


class _DupLoader(yaml.SafeLoader):
    pass


def _parse(text: str):
    """-> (data, lines, errors). Duplicate keys are an error (YAML would silently keep the last one)."""
    errors: list = []
    try:
        root = yaml.compose(text, Loader=_DupLoader)
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        msg = getattr(e, "problem", None) or str(e)
        return {}, {}, [Problem("", (mark.line + 1) if mark else 0, f"the file is not valid YAML ({msg})")]
    if root is None:
        return {}, {}, []
    if not isinstance(root, yaml.MappingNode):
        return {}, {}, [Problem("", 1, "the file must be a list of `key: text` entries")]
    data: dict = {}
    lines: dict = {}
    for knode, vnode in root.value:
        key = str(knode.value)
        line = knode.start_mark.line + 1
        if key in data:
            errors.append(Problem(key, line, f"this key appears twice (first at line {lines[key]})"))
            continue
        lines[key] = line
        try:
            val = _construct(vnode)
        except Exception as e:  # pragma: no cover - defensive
            errors.append(Problem(key, line, f"could not read the value ({e})"))
            continue
        data[key] = val
    return data, lines, errors


def _construct(node):
    ld = yaml.SafeLoader("")
    try:
        return ld.construct_object(node, deep=True)
    finally:
        ld.dispose()


def _fields(template: str) -> tuple:
    """-> (set of placeholder names, error message or None)."""
    try:
        names = {f for _, f, _, _ in string.Formatter().parse(template) if f is not None}
    except ValueError as e:
        return set(), f"bad braces ({e}); write {{{{ for a literal {{"
    return {n.split(".")[0].split("[")[0] for n in names}, None


def validate(data: dict, lines: dict, spec: dict = None, strict_missing: bool = False) -> Report:
    """Check parsed text against the registry. Errors make a file unusable; warnings do not."""
    spec = TEXT_KEYS if spec is None else spec
    rep = Report(keys=len(data))
    for key, val in data.items():
        ln = lines.get(key, 0)
        variants = val if isinstance(val, list) else [val]
        if not variants or not all(isinstance(v, str) and v.strip() for v in variants):
            rep.errors.append(Problem(key, ln, "must be a text, or a list of non-empty texts"))
            continue
        ks: Optional[KeySpec] = spec.get(key)
        if ks is None:
            rep.warnings.append(Problem(key, ln, "unknown key (nothing uses it)"))
            continue
        for i, v in enumerate(variants, 1):
            names, err = _fields(v)
            tag = f" (variant {i})" if len(variants) > 1 else ""
            if err:
                rep.errors.append(Problem(key, ln, err + tag))
                continue
            bad = sorted(names - set(ks.placeholders))
            if bad:
                allowed = ", ".join("{" + p + "}" for p in ks.placeholders) or "no placeholders"
                rep.errors.append(Problem(key, ln, f"unknown placeholder {', '.join('{' + b + '}' for b in bad)}"
                                                   f"{tag}; this key allows {allowed}"))
        if len(variants) < ks.min_variants:
            rep.warnings.append(Problem(key, ln, f"has {len(variants)} variant(s); at least {ks.min_variants} "
                                                 f"are expected so the text does not repeat"))
    for key, ks in spec.items():
        if key not in data and not ks.reserved:
            (rep.errors if strict_missing else rep.warnings).append(
                Problem(key, 0, "missing from the file; the shipped default is used"))
    return rep


class _Lenient(dict):
    def __missing__(self, key):
        return "?"


class TextBank:
    """Variants per key, a shuffle bag per (game, key), and rendering."""

    def __init__(self, data: dict, fallback: Optional["TextBank"] = None, rng: Optional[random.Random] = None,
                 strict: bool = False):
        self.data = {k: (list(v) if isinstance(v, list) else [v]) for k, v in data.items()}
        self.fallback, self.strict = fallback, strict
        self._rng = rng or random.Random()  # its own RNG: never the game's (TXT-2)
        self._bags: dict = {}
        self._last: dict = {}

    # ------------------------------------------------------------ lookups
    def has(self, key: str) -> bool:
        return key in self.data or (self.fallback is not None and self.fallback.has(key))

    def variants(self, key: str) -> list:
        if key in self.data:
            return self.data[key]
        if self.fallback is not None:
            return self.fallback.variants(key)
        if self.strict:
            raise TextError(f"no text for key {key!r}")
        log.error("missing text key %s", key)
        return [f"[{key}]"]

    def count(self, key: str) -> int:
        return len(self.variants(key))

    # ------------------------------------------------------------ selection
    def pick(self, key: str, game=None, variant: Optional[int] = None) -> tuple:
        """-> (index, template). `variant` forces an index (used to re-render a banner with the same wording)."""
        vs = self.variants(key)
        if variant is not None:
            i = variant % len(vs)
            return i, vs[i]
        bag_key = (game, key)
        bag = self._bags.get(bag_key)
        if not bag:
            bag = list(range(len(vs)))
            self._rng.shuffle(bag)
            last = self._last.get(bag_key)
            if len(bag) > 1 and bag[-1] == last:  # the next draw (the end of the list) must not repeat the last one
                bag[0], bag[-1] = bag[-1], bag[0]
            self._bags[bag_key] = bag
        i = bag.pop()
        self._last[bag_key] = i
        return i, vs[i]

    def forget(self, game) -> None:
        for k in [k for k in self._bags if k[0] == game]:
            self._bags.pop(k, None)
            self._last.pop(k, None)

    # ------------------------------------------------------------ rendering
    def render(self, key: str, game=None, variant: Optional[int] = None,
               resolve: Optional[Callable[[int], str]] = None, **vars) -> str:
        return self.render_variant(key, game, variant, resolve, **vars)[1]

    def render_variant(self, key: str, game=None, variant: Optional[int] = None,
                       resolve: Optional[Callable[[int], str]] = None, **vars) -> tuple:
        """-> (index, text). Slot numbers in {player}/{target}/... are named through `resolve` (NAM-2)."""
        idx, tpl = self.pick(key, game, variant)
        vals = dict(vars)
        if resolve is not None:
            for name in SLOT_VARS:
                if isinstance(vals.get(name), int) and not isinstance(vals[name], bool):
                    vals[name] = resolve(vals[name])
            if isinstance(vals.get("players"), (list, tuple)):
                vals["players"] = ", ".join(resolve(s) if isinstance(s, int) else str(s) for s in vals["players"])
        try:
            if self.strict:
                names, err = _fields(tpl)
                if err:
                    raise TextError(f"{key}: {err}")
                missing = names - set(vals)
                if missing:
                    raise TextError(f"{key}: no value for {', '.join(sorted(missing))}")
            return idx, tpl.format_map(_Lenient(vals))
        except (ValueError, IndexError, KeyError, AttributeError) as e:
            if self.strict:
                raise TextError(f"{key}: {e}") from e
            log.error("could not render text key %s: %s", key, e)
            return idx, tpl

    def first(self, key: str, resolve=None, **vars) -> str:
        """Variant 0, no bag: for the archive and the debug console, which must be repeatable."""
        return self.render(key, variant=0, resolve=resolve, **vars)


# ---------------------------------------------------------------- loading
def _read(path) -> str:
    return pathlib.Path(path).read_text(encoding="utf-8")


def load_text(path, fallback: Optional[TextBank] = None, strict_missing: bool = False,
              rng: Optional[random.Random] = None, strict: bool = False) -> tuple:
    """-> (TextBank or None, Report). The bank is None when the file has errors (unreadable or invalid)."""
    try:
        text = _read(path)
    except OSError as e:
        return None, Report(errors=[Problem("", 0, f"could not read {path}: {e}")])
    data, lines, errors = _parse(text)
    rep = validate(data, lines, strict_missing=strict_missing)
    rep.errors = errors + rep.errors
    if rep.errors:
        return None, rep
    return TextBank(data, fallback=fallback, rng=rng, strict=strict), rep


_default_data: Optional[dict] = None


def default_bank(fresh: bool = False, rng: Optional[random.Random] = None, strict: bool = False) -> TextBank:
    """The shipped default file (monke/data/flavour_default.yaml). The parsed file is cached; every call returns a
    bank with its own shuffle bags (and its own RNG if one is given)."""
    global _default_data
    if fresh or _default_data is None:
        bank, rep = load_text(DEFAULT_PATH)
        if bank is None:  # a broken shipped file is a packaging bug: say so loudly
            raise RuntimeError("the shipped flavour file is invalid:\n" + "\n".join(map(str, rep.errors)))
        _default_data = bank.data
    return TextBank(_default_data, rng=rng, strict=strict)


def load_for_use(path, rng=None) -> tuple:
    """Startup (TXT-3): the editable file layered over the shipped default. Invalid text falls back to the shipped
    default and is logged. -> (bank, report, used_default)."""
    base = default_bank(fresh=True, rng=rng)
    bank, rep = load_text(path, fallback=base, rng=rng)
    if bank is None:
        for p in rep.errors:
            log.error("flavour file: %s", p)
        log.error("the flavour file %s is invalid; using the shipped default text", path)
        return base, rep, True
    for p in rep.warnings:
        log.warning("flavour file: %s", p)
    return bank, rep, False
