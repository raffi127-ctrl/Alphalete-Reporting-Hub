"""Rules engine for Carlos's Business & Personal P&L sheet.

Turns a raw bank transaction (Tiller row) into: Category → Group → Side (Business / Personal /
Transfer) and a Flag when the card it was paid on belongs to the other side.

Each rule = (regex on UPPER("full description | description"), category, optional account filter,
optional amount test).  FIRST MATCH WINS, so order matters.  Tiller's own "Transfer" tag is NOT
trusted (it tags ADP payroll, Zelle and checks as transfers); transfers are defined here.
"""
from __future__ import annotations

import datetime as dt
import re

ACCOUNTS = {
    "0573": ("Chase Biz Checking 0573", "B"),
    "7643": ("Chase Biz Card 7643", "B"),
    "0021": ("Chase Recruiting Card 0021", "B"),
    "9005": ("Amex Biz Platinum 9005", "B"),
    "2242": ("Capital One Spark 2242", "B"),
    "5550": ("BofA Card 5550", "P"),
    "5328": ("Chase Personal Checking 5328", "P"),
    "3455": ("Chase Personal Card 3455", "P"),
    "8623": ("Chase Personal Savings 8623", "P"),
    "0253": ("Amex Savings 0253", "P"),
}
BIZ = {"0573", "7643", "0021", "9005", "2242"}
PERS = {"5328", "3455", "5550", "8623", "0253"}

# category -> (group, side)   B business · P personal · X transfer (excluded) · L below-the-line · ? review
CATEGORIES = {
    "Sales Deposits (SCI)": ("Business Income", "B"),
    "Transfer from Security to checking": ("Transfer", "X"),
    "Profit Sharing & JV Income": ("Business Income", "B"),
    "Rent Reimbursement": ("Business Income", "B"),
    "Cash & Check Deposits": ("Business Income", "B"),
    "Other Business Income": ("Business Income", "B"),
    "Commissions & Wages (ADP)": ("Payroll", "B"),
    "Payroll Taxes (ADP)": ("Payroll", "B"),
    "Payroll Fees (ADP)": ("Payroll", "B"),
    "Contractor & Bonus Pay": ("Payroll", "B"),
    "Recruiting - Indeed": ("Recruiting", "B"),
    "Recruiting - ARS": ("Recruiting", "B"),
    "Recruiting - Other": ("Recruiting", "B"),
    "Rent & Facilities": ("Office", "B"),
    "Phone & Internet": ("Office", "B"),
    "Software & Subscriptions": ("Office", "B"),
    "Office Supplies & Equipment": ("Office", "B"),
    "Hub, Accounting & Consulting": ("Office", "B"),
    "Management Fees (Other Offices)": ("Office", "B"),
    "Meals & Team Events": ("Meals & Travel", "B"),
    "Travel": ("Meals & Travel", "B"),
    "Bank Fees & Interest": ("Financial", "B"),
    "Business Taxes (IRS)": ("Financial", "B"),
    "Business Insurance": ("Financial", "B"),
    "Other Business Expense": ("Other", "B"),
    "Owner Draw / Withdrawal": ("Below the Line", "L"),
    "Loan from Raf (received)": ("Below the Line", "L"),
    "Loan Repayment to Raf": ("Below the Line", "L"),
    "Loans & Capital In (other)": ("Below the Line", "L"),
    "Loan Payments (Idea 247)": ("Below the Line", "L"),
    "Paycheck": ("Personal Income", "P"),
    "Other Personal Income": ("Personal Income", "P"),
    "Housing & Utilities": ("Personal", "P"),
    "Groceries": ("Personal", "P"),
    "Food & Dining": ("Personal", "P"),
    "Health & Fitness": ("Personal", "P"),
    "Shopping & Clothing": ("Personal", "P"),
    "Car & Gas": ("Personal", "P"),
    "Subscriptions & Entertainment": ("Personal", "P"),
    "Family, Gifts & Cash": ("Personal", "P"),
    "Personal Insurance": ("Personal", "P"),
    "Personal Taxes": ("Personal", "P"),
    "Personal Travel": ("Personal", "P"),
    "Other Personal": ("Personal", "P"),
    "Bank Fees & Interest (Personal)": ("Personal", "P"),
    "Transfer / Card Payment": ("Transfer", "X"),
    "Uncategorized": ("Review", "?"),
}
SIDE_LABEL = {"B": "Business", "L": "Business", "P": "Personal", "X": "Transfer", "?": "Review"}

R: list = []


def rule(pat, cat, accts=None, amt=None):
    R.append((re.compile(pat), cat, accts, amt))


POS = lambda a: a > 0   # noqa: E731
NEG = lambda a: a < 0   # noqa: E731

# ---- transfers / card payments (own money moving) ----
rule(r"PAYMENT TO CHASE CARD|PAYMENT THANK YOU|MOBILE PAYMENT - THANK YOU|AUTOMATIC PAYMENT - THANK|AUTOPAY PAYMENT", "Transfer / Card Payment")
rule(r"AMERICAN EXPRESS.*ACH PMT|ONLINE PAYMENT .*TO (BANK OF AMERICA|CHASE|AMEX)|APPLECARD GSBANK PAYMENT|CAPITAL ONE.*ONLINE PMT|CAPITAL ONE ONLINE PYMT|PMT FROM BILL|ONLINE/MOBILE PAYMENT CONF|ONLINE PAYMENT - THANK|^PAYMENT - THANK", "Transfer / Card Payment")
rule(r"ONLINE TRANSFER (TO|FROM) (SAV|CHK)|ONLINE TRANSFER FROM|ONLINE TRANSFER TO", "Transfer / Card Payment")
rule(r"BANK OF AMERICA.*(ONLINE PMT|PAYMENT)", "Transfer / Card Payment")
rule(r"ONLINE PAYMENT .*TO", "Transfer / Card Payment", {"5328"})

# ---- Smart Circle ----
rule(r"WF SCILL|SMARTCIRCLE INTL|SMART CIRCLE", "Recruiting - Other", None, NEG)        # SCI debits = background-check account
rule(r"FEDWIRE CREDIT", "Transfer from Security to checking")                             # wires = Security payouts
rule(r"WF SCILL|SMARTCIRCLE INTL|SMART CIRCLE", "Sales Deposits (SCI)")                 # refined per week in split_sci_weeks()

# ---- other business income / below the line ----
rule(r"DANDELION MARKET|PALACE ACQUISITI", "Profit Sharing & JV Income", None, POS)
rule(r"DOMIN8 ACQUISITI", "Rent Reimbursement", None, POS)
rule(r"ALPHALETE MARKET.*ACH", "Loan from Raf (received)", {"0573"}, POS)
rule(r"IDEA 247", "Loans & Capital In (other)", None, POS)
rule(r"IDEA 247", "Loan Payments (Idea 247)")
rule(r"^DEPOSIT$|^DEPOSIT\b", "Cash & Check Deposits", {"0573"}, POS)
rule(r"WIRE REVERSAL.*ADP", "Commissions & Wages (ADP)")
rule(r"REGUS", "Rent & Facilities")
rule(r"^WITHDRAWAL", "Owner Draw / Withdrawal", {"0573"})

# ---- payroll (ADP credits net against these same lines) ----
rule(r"ADP WAGE PAY", "Commissions & Wages (ADP)")
rule(r"ADP TAX|ADP - TAX", "Payroll Taxes (ADP)")
rule(r"ADP PAYROLL FEES|ADP PAY-BY-PAY|PAYROLL CLEARING", "Payroll Fees (ADP)")
rule(r"IRS .*USATAXPYMT|USATAXPYMT", "Business Taxes (IRS)", {"0573"})
rule(r"USATAXPYMT|IRS ", "Personal Taxes")
rule(r"^CHECK #", "Contractor & Bonus Pay", {"0573"})
rule(r"ZELLE PAYMENT TO .*(PAYROLL|PAYCHECK|BONUS|NPA)", "Contractor & Bonus Pay")
rule(r"ZELLE PAYMENT TO NICO MURRUGARRA|ZELLE PAYMENT TO OBADE|ZELLE PAYMENT TO ANTHONY CASTRO", "Contractor & Bonus Pay")
rule(r"ZELLE PAYMENT TO", "Contractor & Bonus Pay", {"0573"})
rule(r"ACH PAYMENT.*TO ALPHALETEMARKETINGGROUPINC", "Contractor & Bonus Pay")

# ---- management fees / other offices (Alphalete Marketing Inc = Maud: $1,400/wk to Sep 2025, $560/wk since) ----
rule(r"ACH PAYMENT.*TO ALPHALETEMARKETING(INC|ORGACCT)", "Management Fees (Other Offices)")
rule(r"ACH PAYMENT.*TO (DAUNTLESS|DOMIN8|DANDELION|FORGE|CGEXECUTIVES|ATOMIC|HIGHVALUE|MOMENTUS|GENERATIONAL|ROMULUS|SOUTHSHORE|MASTERSOFOURREALITY|MOTIV8|MILLENNIUM|MAXIMAL|HIGHLINE|ALISEI|VMC|JGFORTITUDE|KSW|TECHNICAL|OUTOFTHEBOX)", "Management Fees (Other Offices)")
rule(r"MERIAM CORPORATE", "Management Fees (Other Offices)")

# ---- recruiting ----
rule(r"INDEED", "Recruiting - Indeed")
rule(r"ACH PAYMENT.*TO ARS\b", "Recruiting - ARS")
rule(r"JOBS2ME|JAZZHR|RUBIX|RESUME|ZIPRECRUIT|CRAIGSLIST|GLASSDOOR", "Recruiting - Other")

# ---- rent & facilities (business accounts only) ----
rule(r"CCINORTHHWY360|CCI NORTH|PYL POINT PROPERTI|CENTRE POINT|LEASEDIRECT|PRIMO BRANDS|WATERSERV|DYNATROL|OWNER FACTORY|IN OFFICE DALLAS|IN OFFICE TECHN|CULLIGAN|PEST|CINTAS", "Rent & Facilities", BIZ)
rule(r"TG-GUARANTORS", "Business Insurance")

# ---- phone & internet ----
rule(r"ATT\*? ?BILL|AT&T|ATT PAYMENT|UVERSE|RINGCENTRAL|RINGOVER|APTEL|T-MOBILE|VERIZON|SPECTRUM|FRONTIER COMM", "Phone & Internet")

# ---- hub / accounting / consulting ----
rule(r"\bTRUTH\b|CLEGHORN|ARCADIA CONSULTI|IN CONSULTING|IN CONSULTI|HERB-JOY|CG ?EXECUTIVES|MPP\* INVOICE|OFFICIAL CHECKS", "Hub, Accounting & Consulting")

# ---- software ----
rule(r"GOOGLE ?WORKSPACE|GOOGLE \*?WORKSPACE", "Software & Subscriptions")
rule(r"GOOGLE\*|GOOGLE YOUTUBE|GOOGLE STORAGE|GOOGLE ONE|MICROSOFT|SQSP|SQUARESPACE|CALENDLY|CLOUDFLARE|OPENAI|CHATGPT|ANTHROPIC|CLAUDE|ESTREAM|VOICEDROP|PDF\.NET|OCTO BROWSER|ZOOM|DROPBOX|ADOBE|CANVA|SLACK|NOTION|GODADDY|WIX|MAILCHIMP|TWILIO|DOCUSIGN|RIVERSIDE|TASKRABBIT|APPLE\.COM/BILL|FRONTIER AI", "Software & Subscriptions", BIZ)
rule(r"APPLE\.COM/BILL|APPLE COM BILL", "Software & Subscriptions", {"0021", "7643", "9005", "2242"})

# ---- office supplies (business accounts) ----
rule(r"AMAZON|AMZN|BEST ?BUY|APPLE STORE|WALMART\.COM|STAPLES|OFFICE DEPOT|OFFICEMAX|HOME DEPOT|LOWE|UPS STORE|FEDEX|USPS|COSTCO", "Office Supplies & Equipment", BIZ)

# ---- travel ----
rule(r"AMERICAN AIR|AMERICAN AI\b|UNITED|SOUTHWES|DELTA AIR|AEROMEXI|SPIRIT AIRL|JETBLUE|FRONTIER AIRLINES|ALASKA AIR|EXPEDIA|AIRBNB|HOTEL|HILTON|MARRIOTT|SPRINGHILL|RED ROOF|RITZ-CARLTON|BARCELO|INN\b|SUITES|RESORT|CL TRAVEL|TRAVEL|UBER(?! ?EATS)|UBR\*|LYFT|HERTZ|AVIS|ENTERPRISE RENT|PARKING|TOLL|NTTA|RENTAL CAR|DFW AIRPORT|LSU PVS|CLEAR ?\.COM", "Travel", BIZ)
rule(r"AMERICAN AIR|AMERICAN AI\b|UNITED|SOUTHWES|DELTA AIR|AEROMEXI|SPIRIT AIRL|JETBLUE|FRONTIER AIRLINES|EXPEDIA|AIRBNB|HOTEL|HILTON|MARRIOTT|RENAISSANCE|RESORT|UBER(?! ?EATS)|UBR\*|LYFT|CLEAR ?\.COM", "Personal Travel")

# ---- meals ----
FOOD = (r"DOORDASH|DD \*|\bDD [A-Z]|UBER ?EATS|GRUBHUB|RESTAURANT|STEAKHOUSE|STEAKH|GRILL|CAPITAL GRILLE|TST\*?|TST |TACO|CHIPOTLE|"
        r"CHICK-FIL|CHICKFIL|PANDA|TEXAS ROADHOU|SALTGRASS|IN-N-OUT|WINGSTOP|PLUCKERS|MCDONALD|STARBUCKS|COFFEE|PIZZA|SUSHI|BAR &|CAFE|"
        r"KITCHEN|BURGER|WHATABURGER|RAISINGCA|CANE|TORCHY|MEXICAN|CANTINA|MASTROS|MORTON|PERRYS|DAKOTA|CATCH-|SOY COWBOY|MERCURY CHOP|"
        r"RANCH IRVING|RANCH\b|MOXIES|TOPGOLF|GUSTO BAR|P\.F\.CHANG|MARCOS|GREAT PLAINS BEEF|BT\*|VB\b|ME-GRAND PRAI|NICK &|VIVO|SAMS\b|"
        r"ENOCH|MEGAFIT|DEE LINCOLN|PRIME\b|CHOPHOU|BISTRO|TAVERN|BREWING|WINGS")
rule(FOOD, "Meals & Team Events", BIZ)
rule(FOOD, "Food & Dining")

# ---- fees ----
FEES = r"INTEREST CHARGE|PURCHASE INTEREST|LATE FEE|FLEX FOR BUSINESS|STANDARD ACH|STD ACH|RTP/SAME DAY|DOMESTIC INCOMING WIRE|WIRE FEE|MONTHLY SERVICE FEE|ATM FEE|OVERDRAFT|RETURNED|ANNUAL FEE|MEMBERSHIP FEE|FOREIGN TRANS"
rule(FEES, "Bank Fees & Interest", BIZ)
rule(FEES, "Bank Fees & Interest (Personal)")

# ---- personal ----
rule(r"ALPHALETE SPECIA.*PAYROLL|ALPHALETE SPECIALIZED.*PAYROLL", "Paycheck")
rule(r"INTEREST PAYMENT|ZELLE PAYMENT FROM|VENMO CASHOUT|CASH APP.*FROM|TAX REF|REFUND", "Other Personal Income", PERS, POS)
rule(r"LEGACYPARK|LEGACY PARK|REGIONS MORTGAGE|YSI\*|LEX AT LOWRY|CITY OF IRVING|ALLEGRO MAN|PY CONTROL|PEST|JUST ENERGY|ARLINGTON WATER|BLUE SHADE POOLS|ONE HOUR HEATING|TXU|ONCOR|ATMOS|RESIDENT\*|NECTAR|GABRIELA PALACIOS|HOME ?DEPOT|LOWES|IKEA|WAYFAIR|PROPAY|RF ENOCH|TASKRABBIT", "Housing & Utilities")
rule(r"FAMILY HERITAGE|ALLSTATE|GEICO|PROGRESSIVE|STATE FARM|LIBERTY MUTUAL", "Personal Insurance")
rule(r"INSTACART|KROGER|TOM THUMB|H-E-B|HEB\b|WHOLE FOODS|TRADER JOE|ALBERTSONS|SPROUTS|WALMART|TARGET|COSTCO|SAM'?S CLUB|WALGREENS|CVS", "Groceries")
rule(r"LTF|LIFE ?TIME|FITNESS|CPP NATION|ROGUE|ZACHARY MATSUMOTO|ABSOLUTE RECOMP|BARE PERFORMANCE|\bIM8\b|STASIS|GRAYMATTER|THEPITF|ELEV PERFORM|GYM|EQUINOX|CIRCLE MEDICAL|LABCORP|BETTERHELP|MINDFUL|SUPPLEMENT|GNC|VITAMIN|DENTAL|DENTIST|PHARMACY|CHIRO|PHYSIO|DR\.|MD\b|HEALTH", "Health & Fitness")
rule(r"NETFLIX|SPOTIFY|PRIME VIDEO|AUDIBLE|PLAYSTATION|HINGE|TINDER|BUMBLE|HULU|DISNEY|HBO|MAX\.COM|APPLE\.COM/BILL|APPLE COM BILL|STUDIO MOVIE|CINEMARK|AMC\b|TOPGOLF|SPA AT|MASSAGE|NAIL|BARBER|HAIRCUT|SALON|YOUTUBE|PATREON|KINDLE|PARAMOUNT|PEACOCK|SIRIUS|XBOX|NINTENDO|STEAM", "Subscriptions & Entertainment")
rule(r"SUIT ?SUPPLY|MIZZENMAIN|ARITZIA|\bALO\b|ALO-YOGA|SHEIN|SEPHORA|K & G|GQ TAILOR|AERIE|NORDSTROM|MACY|ZARA|H&M|LULULEMON|NIKE|ADIDAS|FOOT LOCKER|AMAZON|AMZN|BEST ?BUY|APPLE STORE|MAGBAK|TAILOR|CLOTH|BOUTIQUE|JEWEL|WATCH|LOUIS|GUCCI|SP [A-Z]", "Shopping & Clothing")
rule(r"SHELL|EXXON|CHEVRON|QT\b|QUIKTRIP|7-ELEVEN|ELEVEN|CIRCLEK|CIRCLE K|RACETRAC|BUC-EE|VALERO|MURPHY|TEXACO|WAWA|GAS\b|FUEL|CAR WASH|AUTOZONE|JIFFY|OIL CHANGE|DISCOUNT TIRE|TOYOTA|HONDA|FORD|BMW|MERCEDES|TESLA|DMV|TXTAG|NTTA|TOLL", "Car & Gas")
rule(r"ZELLE PAYMENT TO|APPLE CASH|CASH APP|VENMO|NON-CHASE ATM|ATM WITHDRAW|PAYPAL|^WITHDRAWAL", "Family, Gifts & Cash", {"5328", "3455", "5550", "8623"})
rule(r"BAIL BOND", "Other Business Expense")

# ---- catch-alls by account side ----
rule(r"UBER|LYFT|EXPEDIA|AIR", "Travel", BIZ)
rule(r"PAYPAL", "Other Business Expense", BIZ)


def _norm(full_desc: str, desc: str) -> str:
    s = f"{full_desc} | {desc}".upper()
    return re.sub(r"ORIG CO NAME:(.*?) ORIG ID", r"\1 ", s)


def category_for(full_desc: str, desc: str, acct: str, amt: float) -> str:
    s = _norm(full_desc, desc)
    for pat, cat, accts, test in R:
        if accts and acct not in accts:
            continue
        if test and not test(amt):
            continue
        if pat.search(s):
            return cat
    return "Uncategorized"


def derived(category: str, acct_side: str) -> tuple[str, str, str]:
    """(group, side label, flag) for a category on an account side ('B' or 'P')."""
    group, cs = CATEGORIES.get(category, ("Review", "?"))
    if cs == "?":
        flag = "Needs category"
    elif cs == "X":
        flag = ""
    else:
        c = "B" if cs in ("B", "L") else "P"
        flag = "" if c == acct_side else ("Business expense on PERSONAL account" if c == "B" else "Personal expense on BUSINESS account")
    return group, SIDE_LABEL[cs], flag


def week_end(d: dt.date) -> dt.date:
    """Saturday of the Sun–Sat week containing d (matches the SCI Financial Report)."""
    return d + dt.timedelta(days=(5 - d.weekday()) % 7)


ACCT_BY_NAME = {name: (num, side) for num, (name, side) in ACCOUNTS.items()}
