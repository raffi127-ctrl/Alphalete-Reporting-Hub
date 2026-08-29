"""Card auto-send rules — each one is a way a real batch has gone wrong.

Nothing here touches Messages: every send path is stubbed, so this is safe to
run on a machine that is signed in and could really text people.
"""
from automations.swag_welcome import imessage as im


def _stub(monkey_state):
    """Swap both send paths for recorders. Returns (calls, restore)."""
    calls = []
    real_text, real_img = im._send_text, im._send_image_via_shortcut
    im._send_text = lambda p, t: calls.append(("text", p))
    im._send_image_via_shortcut = lambda p, a, name=None: (
        calls.append(("card", p)) or "stub")
    def restore():
        im._send_text, im._send_image_via_shortcut = real_text, real_img
    return calls, restore


def _send(**over):
    """One send with the module knobs forced, back to normal afterwards."""
    saved = (im._AUTO_SEND_CARD, im._MIN_MACOS_FOR_CARDS, im.shortcut_installed)
    im._AUTO_SEND_CARD = over.get("auto", True)
    im._MIN_MACOS_FOR_CARDS = over.get("min_macos", 0)
    im.shortcut_installed = lambda name=im.SHORTCUT_NAME: over.get("shortcut", True)
    calls, restore = _stub(None)
    try:
        res = im.send("+15551234567", "hi", attachment=over.get("att", "x.png"),
                      dry_run=over.get("dry", False))
    finally:
        restore()
        im._AUTO_SEND_CARD, im._MIN_MACOS_FOR_CARDS, im.shortcut_installed = saved
    return res, calls


def test_capable_machine_sends_the_card():
    res, calls = _send()
    assert res["sent"] and res["image_auto_sent"], res
    assert [c[0] for c in calls] == ["text", "card"], calls


def test_old_macos_reports_instead_of_claiming_a_send():
    # macOS 15 runs the Shortcut, exits 0 and delivers NOTHING. Never report
    # that as a card sent — 54 hires with no photo looked like a success once.
    res, calls = _send(min_macos=999)
    assert res["sent"], res
    assert res["image_auto_sent"] is False
    assert "macOS" in res["image_error"]
    assert [c[0] for c in calls] == ["text"], calls


def test_missing_shortcut_names_itself():
    res, _ = _send(shortcut=False)
    assert res["image_auto_sent"] is False
    assert im.SHORTCUT_NAME in res["image_error"]


def test_switch_off_says_so():
    res, _ = _send(auto=False)
    assert res["image_auto_sent"] is False
    assert "switched off" in res["image_error"]


def test_dry_run_sends_nothing():
    res, calls = _send(dry=True)
    assert res["dry_run"] and not res["sent"] and not calls, (res, calls)


def test_non_phone_never_reaches_the_shortcut():
    # A non-number is what parks a "No recipients" compose sheet on someone's
    # screen — the gate has to refuse before `shortcuts run`.
    for bad in ("discover", "", "n/a", "ask JD"):
        assert not im._looks_like_phone(bad), bad
    for good in ("+14695890574", "(469) 589-0574", "4695890574"):
        assert im._looks_like_phone(good), good


if __name__ == "__main__":
    fails = 0
    for n, f in sorted(globals().items()):
        if n.startswith("test_") and callable(f):
            try:
                f()
                print("ok  ", n)
            except AssertionError as e:
                fails += 1
                print("FAIL", n, "|", e)
    raise SystemExit(1 if fails else 0)
