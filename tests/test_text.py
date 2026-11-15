"""TXT tests: every key exists with enough variants, placeholders are known, the bag never repeats back-to-back,
an invalid reload leaves the old text active, and the engine contains no prose."""
import pathlib
import random
import re

import pytest

from monke.text.bank import (DEFAULT_PATH, TextBank, TextError, default_bank, load_for_use, load_text, validate,
                             _parse)
from monke.text.keys import TEXT_KEYS

ROOT = pathlib.Path(__file__).resolve().parent.parent
FLAVOUR = ROOT / "flavour.yaml"


def test_the_editable_file_is_valid_and_complete():
    """flavour.yaml is yours to edit: more variants are fine; broken YAML, bad placeholders or deleted keys are not."""
    bank, rep = load_text(FLAVOUR, strict_missing=True)
    assert bank is not None, [str(e) for e in rep.errors]
    for key, spec in TEXT_KEYS.items():
        assert spec.reserved or bank.has(key), key


def test_the_shipped_default_is_valid_and_complete():
    path = DEFAULT_PATH
    bank, rep = load_text(path, strict_missing=True)
    assert bank is not None, [str(e) for e in rep.errors]
    assert [str(w) for w in rep.warnings] == []  # no unknown keys, no missing keys, no thin variant lists
    for key, spec in TEXT_KEYS.items():
        if spec.reserved and not bank.has(key):
            continue
        assert bank.count(key) >= spec.min_variants, key


def test_every_variant_renders_with_sample_values():
    bank = default_bank(strict=True)
    for key, spec in TEXT_KEYS.items():
        if not bank.has(key):
            continue
        sample = {p: ("x" if p not in ("count", "needed", "alive", "day", "night", "slot") else 3)
                  for p in spec.placeholders}
        for i in range(bank.count(key)):
            assert bank.render(key, variant=i, **sample)


def test_the_bag_never_repeats_back_to_back_and_covers_all_variants():
    bank = TextBank({"k": ["a", "b", "c", "d"]}, rng=random.Random(1))
    draws = [bank.render("k", game="g") for _ in range(40)]
    assert all(a != b for a, b in zip(draws, draws[1:]))
    for i in range(0, 40, 4):
        assert sorted(draws[i:i + 4]) == ["a", "b", "c", "d"]  # a whole bag before anything repeats


def test_text_has_its_own_rng_not_the_games():
    game_rng = random.Random(5)
    before = random.Random(5).random()
    bank = TextBank({"k": ["a", "b", "c"]})
    for _ in range(10):
        bank.render("k", game="g")
    assert game_rng.random() == before


def test_slots_are_named_through_the_resolver_and_extra_values_are_ignored():
    bank = TextBank({"k": "**{player}** voted for **{target}**."})
    assert bank.render("k", resolve=lambda s: f"P{s}", player=3, target=5, count=9) == "**P3** voted for **P5**."


def test_errors_are_reported_with_key_and_line():
    text = 'good: "fine {player}"\nbad.placeholder: "hello {nonsense}"\ngood: "again"\nbad.braces: "oops {"\n'
    data, lines, errs = _parse(text)
    assert any("appears twice" in e.message and e.line == 3 for e in errs)
    spec = {"bad.placeholder": TEXT_KEYS["dawn.no_deaths"], "bad.braces": TEXT_KEYS["dawn.no_deaths"]}
    rep = validate(data, lines, spec)
    msgs = [str(e) for e in rep.errors]
    assert any("line 2" in m and "{nonsense}" in m for m in msgs)
    assert any("line 4" in m and "braces" in m for m in msgs)


def test_bad_yaml_is_reported_with_a_line(tmp_path):
    f = tmp_path / "f.yaml"
    f.write_text("a: [unclosed\nb: 2\n")
    bank, rep = load_text(f)
    assert bank is None and rep.errors and rep.errors[0].line >= 1


def test_startup_with_invalid_text_falls_back_to_the_shipped_default(tmp_path):
    f = tmp_path / "f.yaml"
    f.write_text('dawn.no_deaths: "uses {bogus}"\n')
    bank, rep, used_default = load_for_use(f)
    assert used_default and rep.errors
    assert bank.render("dawn.no_deaths")  # the shipped default works


def test_a_valid_file_with_missing_keys_falls_back_per_key(tmp_path):
    f = tmp_path / "f.yaml"
    f.write_text('dawn.no_deaths: ["Quiet.", "Calm.", "Still."]\n')
    bank, rep, used_default = load_for_use(f)
    assert not used_default and rep.warnings
    assert bank.render("dawn.no_deaths", variant=0) == "Quiet."
    assert bank.render("phase.paused")  # missing from the file: the default is used


def test_a_missing_key_at_runtime_never_crashes_a_game():
    bank = TextBank({})
    assert bank.render("nope.nothing") == "[nope.nothing]"
    with pytest.raises(TextError):
        TextBank({}, strict=True).render("nope.nothing")


def test_strict_mode_catches_a_missing_variable():
    with pytest.raises(TextError):
        TextBank({"k": "{player} and {target}"}, strict=True).render("k", player="x")


def test_role_keys_are_generated_from_the_role_registry():
    from monke.roles import all_defs
    for d in all_defs():
        for suffix in ("intro", "goal", "tips", "reveal", "wiki", "name"):
            assert f"role.{d.id}.{suffix}" in TEXT_KEYS
        for ab in d.abilities:
            assert f"ability.{d.id}.{ab.id}.label" in TEXT_KEYS


def test_the_engine_and_roles_contain_no_prose():
    """Every Rejected and text_key in the engine and role code is a key in the registry (TXT-2)."""
    src = ""
    for sub in ("engine", "roles"):
        for f in (ROOT / "monke" / sub).glob("*.py"):
            src += f.read_text()
    literals = set(re.findall(r'"((?:[a-z_0-9]+\.)+[a-z_0-9]+)"', src))
    keyish = {l for l in literals if l.split(".")[0] in {"error", "attack", "block", "jail", "jailor", "jester", "vet",
                                                          "sk", "mafia", "sheriff", "consig", "doctor", "phase",
                                                          "admin", "trial", "dawn"}}
    assert keyish, "found no keys at all: the scan is broken"
    assert not [k for k in keyish if k not in TEXT_KEYS], sorted(k for k in keyish if k not in TEXT_KEYS)
    assert not re.search(r'Rejected\("[^"]* [^"]*"', src)  # no sentence passed to Rejected
    assert not re.search(r'\btext=f?"', src)  # events carry text_key, never text


def test_reload_swaps_a_valid_file_and_rejects_an_invalid_one(tmp_path):
    from monke.adapter.bot import MonkeBot
    f = tmp_path / "flavour.yaml"
    f.write_text(FLAVOUR.read_text(encoding="utf-8").replace('dawn.no_deaths:', 'dawn.no_deaths:', 1), encoding="utf-8")
    import os
    os.environ["MONKE_FLAVOUR"] = str(f)
    try:
        bot = MonkeBot(str(tmp_path / "m.db"))
    finally:
        del os.environ["MONKE_FLAVOUR"]
    assert not bot.text_is_default
    before = bot.presenter.composer.bank
    f.write_text('dawn.no_deaths: "{nonsense}"\n', encoding="utf-8")
    ok, rep = bot.reload_text()
    assert not ok and rep.errors and bot.presenter.composer.bank is before  # the old text stays active
    f.write_text('dawn.no_deaths: ["A.", "B.", "C."]\n', encoding="utf-8")
    ok, rep = bot.reload_text()
    assert ok and bot.presenter.composer.bank is not before
    assert bot.presenter.composer.bank.render("dawn.no_deaths", variant=1) == "B."
    assert bot.presenter.composer.bank.render("phase.paused")  # other keys fall back to the shipped default
