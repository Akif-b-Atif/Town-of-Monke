from types import SimpleNamespace

from monke.adapter.setup_cog import commands_overwrites


def test_commands_overwrites_shape():
    everyone, me, admin = object(), object(), object()
    guild = SimpleNamespace(default_role=everyone, me=me)
    ow = commands_overwrites(guild, admin)
    assert ow[everyone].view_channel is True
    assert ow[everyone].send_messages is False
    assert ow[admin].send_messages is True
    assert ow[me].manage_channels is True