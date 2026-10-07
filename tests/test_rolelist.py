import random

import pytest

from monke.engine.rolelist import generate_roles, validate_rolelist
from monke.errors import Rejected


def v(tokens, n=None):
    return validate_rolelist(tokens, n or len(tokens))


def test_valid_list_and_aliases():
    assert v(["jailor", "GODFATHER", "ti", "tp", "Serial Killer"])[-1] == "serial_killer"


@pytest.mark.parametrize("tokens,n", [
    (["Jailor", "Godfather", "TI", "TP"], 4),                              # too few players
    (["Jailor", "Godfather", "TI", "TP", "TS"], 6),                        # count mismatch
    (["Jailor", "Godfather", "TI", "TP", "Banana"], 5),                    # unknown token
    (["Jailor", "Jailor", "Godfather", "TP", "TS"], 5),                    # two Jailors
    (["Jailor", "TI", "TP", "TS", "RT"], 5),                               # no Godfather
])
def test_invalid(tokens, n):
    with pytest.raises(Rejected):
        validate_rolelist(tokens, n)


def test_pool_exhaustion_and_uniqueness():
    with pytest.raises(Rejected):
        generate_roles(v(["Jailor", "Godfather", "TK", "TK", "TI"]), random.Random(1))
    with pytest.raises(Rejected):
        generate_roles(v(["Jailor", "Godfather", "MK", "MK", "TI"]), random.Random(1))


def test_random_tokens_never_pick_leaders():
    for seed in range(50):
        roles = generate_roles(v(["Jailor", "Godfather", "RT", "RT", "RM"]), random.Random(seed))
        assert roles.count("jailor") == 1 and roles.count("godfather") == 1


def test_deterministic_by_seed():
    toks = v(["Jailor", "Godfather", "RT", "RT", "RM", "TK", "NK"])
    assert generate_roles(toks, random.Random(7)) == generate_roles(toks, random.Random(7))
