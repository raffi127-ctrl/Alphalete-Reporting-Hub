"""Finding an enrolling office by its OwnerVille ACCOUNT NUMBER.

Row shape is the one knocks_access_watch.audit.classify reads: [office number,
company, owner, ..., action]. The two must not drift — the audit and the
enrollment have to agree about what a row says.
"""
from automations.disposition_signup import resolve_office as RO
from automations.disposition_signup.schema import DispositionRecord

# Real spellings this repo has been bitten by: OwnerVille says "Calvin Ribera",
# everyone says "Rivera"; it says "Akashdeep Rai", the board says "Kash Rai".
ROWS = [
    ["11280", "Alphalete Inc.", "Rafael Hidalgo", "", ""],
    ["22162", "Vernon, Inc.", "Calvin Ribera", "", ""],
    ["22177", "Palace Acquisitions, Inc.", "Akashdeep Rai", "", ""],
    ["19910", "Rude Holdings", "Floyd Rude", "", "Request Sent"],
    ["21959", "Clear View Consultants, Inc.", "Jay Turnage", "", ""],
]


def _rec(**kw):
    base = dict(key="calvin", owner="Calvin Rivera", ov_account="22162",
                knocks_office="", requested_by="Calvin")
    base.update(kw)
    return DispositionRecord(**base)


# --- the number is what cannot be spelled two ways --------------------------

def test_the_account_number_finds_an_office_whose_name_drifted():
    """"Calvin Rivera" matches no row. 22162 does."""
    row, how = RO.match_row(ROWS, account="22162", names=["Calvin Rivera"])
    assert how == "account"
    assert RO.owner_of(row) == "Calvin Ribera"


def test_a_decorated_account_number_still_matches():
    for typed in ("#22162", " 22162 ", "22162.0", "acct 22162"):
        row, how = RO.match_row(ROWS, account=typed)
        assert RO.owner_of(row) == "Calvin Ribera", typed


def test_the_name_is_still_the_fallback():
    """A mistyped number must not be worse than before this existed."""
    row, how = RO.match_row(ROWS, account="99999",
                            names=["Jay Turnage"])
    assert how == "name"
    assert RO.account_of(row) == "21959"


def test_no_number_and_no_known_spelling_is_a_miss():
    row, how = RO.match_row(ROWS, account="", names=["Calvin Rivera"])
    assert row is None and how == ""


def test_a_miss_names_the_near_rows():
    """The 2026-08-24 case: OwnerVille calls Wayne Rude "Floyd Rude", so the
    surname is what points at the right row. It carries the office number and
    the access state, because a near match is only worth an alias if that
    office is actually granted."""
    near = RO.near_rows(ROWS, "Wayne Rude")
    assert near and "Floyd Rude" in near[0]
    assert "19910" in near[0] and "pending" in near[0]


def test_the_hint_cannot_help_when_the_surname_itself_is_misspelled():
    """"Rivera" is not in "Ribera" — which is exactly why the account number
    is the primary match and this is only a hint."""
    assert RO.near_rows(ROWS, "Calvin Rivera") == []


def test_near_rows_ignores_a_surname_too_short_to_mean_anything():
    assert RO.near_rows(ROWS, "Bob Li") == []


# --- granted vs waiting on the owner ----------------------------------------

def test_request_sent_is_pending_not_granted():
    row, _ = RO.match_row(ROWS, account="19910")
    assert RO.access_state(row) == RO.PENDING


def test_a_blank_action_means_granted():
    row, _ = RO.match_row(ROWS, account="22162")
    assert RO.access_state(row) == RO.GRANTED


# --- the alias that stops this happening twice ------------------------------

def test_ownervilles_spelling_is_filed_as_an_alias():
    """Canonical = what we file them under (what the owner typed); alias =
    OwnerVille's spelling. That is the direction impersonation reads."""
    row, _ = RO.match_row(ROWS, account="22162")
    pair = RO.alias_needed(_rec(), row, aliases={})
    assert pair == ("Calvin Rivera", "Calvin Ribera")


def test_no_alias_is_filed_when_the_spelling_already_matches():
    row, _ = RO.match_row(ROWS, account="21959")
    assert RO.alias_needed(_rec(key="jay", owner="Jay Turnage",
                                ov_account="21959"), row, aliases={}) is None


def test_the_company_name_counts_as_a_spelling_we_already_search():
    """An owner who put the company in `knocks_office` is not a mismatch."""
    row, _ = RO.match_row(ROWS, account="22162")
    rec = _rec(owner="Calvin Rivera", knocks_office="Calvin Ribera")
    assert RO.alias_needed(rec, row, aliases={}) is None


def test_an_existing_alias_row_means_nothing_new_to_file():
    row, _ = RO.match_row(ROWS, account="22162")
    aliases = {"Calvin Rivera": ["Calvin Ribera"]}
    assert RO.alias_needed(_rec(), row, aliases=aliases) is None


def test_describe_says_number_state_and_how():
    row, how = RO.match_row(ROWS, account="19910")
    line = RO.describe(row, how)
    assert "19910" in line and "pending" in line and "account" in line
