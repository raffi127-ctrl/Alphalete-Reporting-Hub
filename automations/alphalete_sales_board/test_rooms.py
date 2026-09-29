"""Which room gets which board (Raf 2026-09-28: "all of it" moves to the
Knocking Chat A-Players; Partners and the A-Team get nothing from Lucy)."""
from pathlib import Path

from automations.alphalete_sales_board import config as C

ROOT = Path(__file__).resolve().parents[2]


def test_every_board_goes_to_the_knocking_chat_not_the_old_rooms():
    boards = C.LIVE_GROUPS + C.END_OF_DAY_GROUPS + C.TIMES_GROUPS + [C.REPLY_GROUP]
    assert C.GROUP_KNOCKING in C.LIVE_GROUPS
    assert C.GROUP_KNOCKING in C.END_OF_DAY_GROUPS
    assert C.GROUP_KNOCKING in C.TIMES_GROUPS
    assert C.GROUP_PARTNERS not in boards
    assert C.GROUP_A_TEAM not in boards


def test_the_reply_reader_listens_where_the_answers_go():
    """The reader (a separate LaunchAgent) and apply_replies must name the
    same room, or "Bo=Kelvinton" typed in the chat is never seen."""
    plist = (ROOT / "deploy" / "com.alphalete.sales-text-reader.plist").read_text()
    assert "<string>%s</string>" % C.REPLY_GROUP in plist
    assert "Alphalete Partners" not in plist


def test_nothing_texts_the_lvl1_imessage_room():
    """Raf 2026-09-29: "Can we stop all post on this channel, it doesn't get
    used" -- the Lvl 1's iMessage room gets nothing from Lucy (Slack
    #alphalete-lvl1-chat is a different room and keeps its posts)."""
    from automations.new_start_followup import group_reminders as GR
    boards = C.LIVE_GROUPS + C.END_OF_DAY_GROUPS + C.TIMES_GROUPS + [C.REPLY_GROUP]
    assert C.GROUP_LVL1 not in boards
    assert GR.IMESSAGE_ON is False
