from monke.adapter.planner import commands_channel_plan


def test_everyone_can_read_but_not_write():
    p = commands_channel_plan()["everyone"]
    assert p["view_channel"] is True
    assert p["read_message_history"] is True
    for name in ("send_messages", "add_reactions", "create_public_threads",
                 "create_private_threads", "use_application_commands"):
        assert p[name] is False


def test_admin_can_write_and_use_commands():
    p = commands_channel_plan()["admin"]
    assert p["send_messages"] is True
    assert p["use_application_commands"] is True


def test_bot_keeps_full_access():
    p = commands_channel_plan()["bot"]
    for name in ("view_channel", "read_message_history", "send_messages", "embed_links"):
        assert p[name] is True


def test_plan_is_a_copy():
    a = commands_channel_plan()
    a["everyone"]["send_messages"] = True
    assert commands_channel_plan()["everyone"]["send_messages"] is False