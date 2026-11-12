"""The ApplicantStream calendar's own date navigation, as a plain string.

MOVED HERE 2026-11-11 so it can SHIP. `office_admin.fdot` needs it to read a
week of the training calendar, and fdot runs on an office computer -- which
cannot import `raf_daily_update.run`, where this used to live: that module is
one of Alphalete's own and reaches for things an office Mac has no access to.

It is a STRING. Nothing here imports anything, which is the point: a constant
that lives inside a module nobody else can load is a constant somebody copies,
and a second copy of a page script is how two callers come to drive the same
page differently.
"""
from __future__ import annotations

# Set the picker, tell the calendar widget to navigate, and report back through
# a body attribute -- the page offers no promise we can await.
CAL_NAV_JS = r"""(d) => {
    const s = document.createElement('script');
    s.textContent = `try { if (window.jQuery) jQuery("#topLevelDatePicker").val("${d}");
        if (window.cal) { cal.currentDate = "${d}"; cal.currentDateLocale = "${d}"; cal.navigate(); }
        document.body.setAttribute('data-calnav', window.cal ? 'ok' : 'nocal');
    } catch (e) { document.body.setAttribute('data-calnav', 'err'); }`;
    document.head.appendChild(s);
    return document.body.getAttribute('data-calnav');
}"""
