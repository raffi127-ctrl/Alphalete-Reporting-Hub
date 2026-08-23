"""Turn an AppStream Source Report table into one row per REAL ad.

The report is one row per ad-title *variant*, plus a lot of non-ad noise. Indeed
splits a single posting several ways and every split has to be folded back
together or one ad shows up as several rows — the ", N locations" suffix alone
once fragmented 1,303 applicants across four rows.
"""
from __future__ import annotations

import io
import re
from collections import OrderedDict

import pandas as pd

FIELDS = ['apps', 'removed', 'scl', 'b1', 's1', 'b2', 's2', 'tb', 'ts', 'nb', 'ns']

NOISE = re.compile(
    r'new message from|new contact form|contact page|feedback|recommend indeed|'
    r'action required|payment|invoice|billing|your .* job in |visibility|appeal|'
    r'sponsored|product update|survey|resumes - ziprecruiter|weekly job summary|'
    r'career fair|applicant list expires|instagram|google |privacy|welcome to |'
    r'^re:|^today\'s |thanks for your|our meeting|catch up on|see what|'
    r'recently added|new deals|talks ai|trust signal|headed to indeed|'
    r'register (by|today)|moments you|'
    # Indeed's own account / marketing mail lands in these inboxes too.
    r'indeed\s*[:|]|your indeed|employer account|what\'s new|impressions|'
    r'offer letter|digest ready|more replies|profiles like|client ask|'
    # 2026-08-23 sweep (Jamis's tab): transactional/marketing subjects that got
    # past the first net. \w\? catches mojibake-apostrophe sentences
    # ("you?ve") and marketing questions ("texts? Sona...") — a REAL title's
    # "?" separator is always space-padded, which this deliberately skips.
    r'indeed\.com|your account\b|\bpassword\b|apple account|missed calls|'
    r'agency partnership|white.?label|sports craft|promotional events|'
    r'\w\?|'
    # " @ Employer" is a resume-scooper artifact naming the candidate's CURRENT
    # job, never one of our own ad titles.
    r'\s@\s', re.I)

# Indeed appends ", N locations" to a posting that targets several cities. It
# sits exactly where "City, ST" normally goes, so it must come off FIRST.
LOCSUF = re.compile(r',\s*\d+\s*locations?\s*$', re.I)
QUAL = re.compile(r'\s*[|\-–]\s*(weekly pay|training provided|career growth|'
                  r'entry level(?: marketing)?)\s*$', re.I)
LANG = re.compile(r'\s*[\(\*\-]{0,2}\s*(spanish needed|bilingual spanish required|'
                  r'spanish necessary|arabic required|spanish required|bilingual)'
                  r'\s*[\)\*\-]{0,2}\s*', re.I)
# AppStream sometimes splits a word's first letter ("S ales", "E ntry"). Rejoin,
# but never the real words I / A.
SPLITCAP = re.compile(r'\b(?![IA]\b)([A-Z])\s+([a-z]{3,})')
CITY_ABBR = [(r'^Ft\.?\s+', 'Fort '), (r'^St\.?\s+', 'Saint '), (r'^Mt\.?\s+', 'Mount '),
             (r'^N\.?\s+', 'North '), (r'^S\.?\s+', 'South '), (r'^E\.?\s+', 'East '),
             (r'^W\.?\s+', 'West '), (r'\bHgts\.?\b', 'Heights')]


def blank():
    return dict.fromkeys(FIELDS, 0)


def num(v):
    try:
        f = float(v)
        return 0 if pd.isna(f) else int(f)
    except Exception:  # noqa: BLE001 — a blank or '—' cell is simply zero
        return 0


def clean(t):
    return re.sub(r'\s\?\s', ' – ', SPLITCAP.sub(r'\1\2', t))


def tidy(t):
    """Collapse whitespace and drop the punctuation a stripped qualifier leaves
    behind: "... Associate (Spanish Needed)." -> "... Associate ." would never
    match the plain title."""
    t = re.sub(r'\(\s*\)', ' ', t)
    return re.sub(r'\s+', ' ', t).strip().strip(' .,;:-–|').strip()


def norm_city(c):
    if not c or ',' not in c:
        return c
    name, st = c.rsplit(',', 1)
    name = ' '.join(name.split())
    for pat, rep in CITY_ABBR:
        name = re.sub(pat, rep, name, flags=re.I)
    return '%s, %s' % (name.strip(), st.strip().upper())


def split_city(subject):
    s = LOCSUF.sub('', subject.strip()).strip().rstrip(',').strip()
    m = re.match(r"^(.*),\s*([A-Za-z .'-]+),\s*([A-Z]{2})$", s)
    if m:
        return m.group(1).strip(), norm_city('%s, %s' % (m.group(2).strip(), m.group(3)))
    return s, ''


def base_role(t):
    return tidy(QUAL.sub('', LANG.sub(' ', LOCSUF.sub('', t))))


def core_title(t):
    t, prev = base_role(t), None
    while prev != t:
        prev = t
        t = tidy(QUAL.sub('', t))
    return t


def show(t):
    return re.sub(r'\s*\.\s*$', '', t).strip()


def account_name(inbox):
    dom = inbox.split('@')[-1].split('.')[0]
    return re.sub(r'(inc|llc|group|marketing)$', r' \1', dom).replace('-', ' ').title()


def load_table(html):
    """Parse one Source Report table into per-ad records."""
    d = pd.read_html(io.StringIO(html))[0]
    ads = []
    for _, r in d.iterrows():
        subj, inbox = r.get('Email Subject Line'), r.get('Email Inbox')
        if not isinstance(subj, str) or not subj.strip():
            continue                       # subtotal / spacer row
        if not isinstance(inbox, str) or inbox.strip() in ('', '—'):
            continue
        if NOISE.search(subj):
            continue
        if not re.search(r'[A-Z]', subj):
            continue                       # all-lowercase = a sentence, not an ad title
        title, city = split_city(clean(subj))

        def col(*names):
            for n in names:
                if n in d.columns:
                    return num(r[n])
            return 0

        rec = blank()
        rec.update(apps=num(r['Process Emails']),
                   removed=num(r['Removed From Process Emails']),
                   scl=num(r['Sent to Call List']),
                   b1=num(r['First Interviews Booked']),
                   s1=num(r['First Interviews Marked Showed Up']),
                   b2=num(r['Second Interviews Booked']),
                   s2=num(r['Second Interviews Showed-up']),
                   # Column sets differ per office: some report a Training stage
                   # and First Day of Sales, others only Brought on Board.
                   tb=col('First Day of Training Booked'),
                   ts=col('First Day of Training Showed Up'),
                   nb=col('First Day of Sales Booked', 'Brought on Board'),
                   ns=col('First Day of Sales Showed Up', 'Brought on Board Showed Up'))
        ads.append(dict(inbox=inbox.strip(), title=title, city=city,
                        base=base_role(title), rec=rec))
    return ads


def merge(ads, keyfn, titlefn):
    out = OrderedDict()
    for a in ads:
        k = keyfn(a)
        g = out.setdefault(k, dict(a, rec=blank(), variants=0, titles=[]))
        for f in FIELDS:
            g['rec'][f] += a['rec'][f]
        g['variants'] += 1
        g['titles'].append(a['title'])
    for g in out.values():
        g['title'] = titlefn(g)
    return list(out.values())


def qualifier(titles):
    for t in titles:
        m = LANG.search(t)
        if m:
            return m.group(1).lower()
    return ''


def apply_city_rule(groups):
    """A multi-location posting arrives with no city. Fold it into the account's
    city ad when that account runs the role in exactly one city; with two or
    more, match the language wording; if that can't decide, leave it alone and
    flag it rather than guess."""
    by = OrderedDict()
    for g in groups:
        by.setdefault((g['inbox'], g['base'].lower()), []).append(g)
    out, flags = [], []
    for (inbox, base), gs in by.items():
        blanks = [g for g in gs if not g['city']]
        cities = [g for g in gs if g['city']]
        if not blanks or not cities:
            out.extend(gs)
            continue
        for b in blanks:
            target = None
            if len(cities) == 1:
                target = cities[0]
            else:
                q = qualifier(b['titles'])
                match = [c for c in cities if qualifier(c['titles']) == q]
                if len(match) == 1:
                    target = match[0]
            if target is None:
                flags.append((inbox, base, sorted(c['city'] for c in cities),
                              b['rec']['apps']))
                out.append(b)
            else:
                for f in FIELDS:
                    target['rec'][f] += b['rec'][f]
                target['variants'] += b['variants']
                target['titles'].extend(b['titles'])
                target['title'] = show(min(target['titles'], key=len))
        out.extend(cities)
    return out, flags


def merge_across_cities(groups):
    """One row per (inbox, base role) regardless of city — the cities are
    listed together in the City column instead. Carlos's rule for his own
    dashboard (2026-08-22): same account + same role = one ad, no matter
    where it runs; different accounts stay separate. Blank-city pieces fold
    in too, so nothing needs flagging."""
    out = OrderedDict()
    for g in groups:
        k = (g['inbox'], g['base'].lower())
        t = out.setdefault(k, dict(g, rec=blank(), variants=0, titles=[],
                                   cities=[]))
        for f in FIELDS:
            t['rec'][f] += g['rec'][f]
        t['variants'] += g['variants']
        t['titles'].extend(g['titles'])
        if g['city'] and g['city'] not in t['cities']:
            t['cities'].append(g['city'])
    res = []
    for t in out.values():
        t['title'] = show(min(t['titles'], key=len))
        t['city'] = ' + '.join(t.pop('cities'))
        res.append(t)
    res.sort(key=lambda g: -g['rec']['apps'])
    return res


def ads_for_month(html):
    """Merged, city-resolved ad rows for one office-month, plus any flags."""
    ads = load_table(html)
    m = merge(ads, lambda a: (a['inbox'], a['base'].lower(), a['city'].lower()),
              lambda g: show(min(g['titles'], key=len)))
    m, flags = apply_city_rule(m)
    m.sort(key=lambda g: -g['rec']['apps'])
    return m, flags


def ytd_from(all_ads):
    """Roll a manager's months together purely by core ad title."""
    y = merge(all_ads, lambda a: core_title(a['title']).lower(),
              lambda g: show(core_title(min(g['titles'], key=len))))
    y.sort(key=lambda g: (-g['rec']['b2'], -g['rec']['apps']))
    return y


def ratio(n, d):
    return (n / d) if d else ''


def display(account, inbox, title, city, variants, r):
    """The 19 dashboard columns, in sheet order."""
    return [account, inbox, title, city, variants, r['apps'],
            ratio(r['removed'], r['apps']), r['scl'], r['b1'], r['s1'],
            ratio(r['s1'], r['b1']), r['b2'], r['s2'], ratio(r['s2'], r['b2']),
            r['tb'], r['ts'], r['nb'], r['ns'], ratio(r['b2'], r['scl'])]
