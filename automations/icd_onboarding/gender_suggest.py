"""A gender SUGGESTION from a first name — only where it is clear.

WHY THIS EXISTS AND WHAT CHANGED. Gender was a hand-only column, and the
reason was written into three different modules: "Nothing guesses it -- a
guess here goes onto a payroll record." That reason still stands, and it is
why this module is shaped the way it is. What changed is who does the typing
(Megan, 2026-11-18):

    "gender pre-filled from the first name, and confirmed. Lucy fills in a
    suggestion; the admin accepts it or changes it. Decided this way because
    it lands on a payroll record -- this week's own list has Ayodele,
    Marquette, Jovani, Penina, Sumera, Toni and Carmen on it. Only guesses
    where it's clear, leaves the rest blank, and never overwrites a typed
    answer."

So the suggestion is NOT an answer. Four rules, and all four are enforced
here rather than left to a caller to remember:

  1. ONLY WHERE IT IS CLEAR. A name has to be on a curated list of names that
     are overwhelmingly one way in the US. Everything else is blank -- not a
     best guess, blank. A list that tried to cover every name would be a list
     of coin flips, and a coin flip on a payroll record is worse than an
     empty cell somebody has to fill, because the empty cell gets filled.
  2. KNOWN-AMBIGUOUS NAMES ARE ALWAYS BLANK, even if a list somewhere would
     claim them. Megan's seven are in that set by name. They are not edge
     cases we tolerate -- they are the reason the feature is a suggestion and
     not an automation.
  3. IT NEVER OVERWRITES. Anyone whose cell already holds anything is left
     out of the plan entirely, so a typed answer cannot be replaced by a
     guess, and re-running cannot undo somebody's correction.
  4. IT IS MARKED AS A SUGGESTION. The cell is tinted (board.SUGGESTED), the
     same two-state idiom Blue Ink uses: a tint is a machine saying "I filled
     this in", a plain cell is a person saying "this is right". The admin
     accepting it clears the tint; nothing here reads the tint back, so an
     accepted answer and a hand-typed one behave identically from then on.

WHAT WOULD MAKE THIS WRONG TO EXTEND. Adding names to make the coverage look
better is the one change that breaks it. The measure of this module is not how
many cells it fills -- it is that every cell it DOES fill is right. If a name
is arguable, it belongs in AMBIGUOUS, and the admin types it.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Dict, List, Sequence

from automations.icd_onboarding import board as B

# Exactly how Apex's dropdown spells them (see apex_new_starts.values._gender),
# so an accepted suggestion is typed into Apex unchanged.
FEMALE = "Female"
MALE = "Male"

# --- NAMES THAT ARE NOT CLEAR ------------------------------------------------
# These are always blank. The first seven are Megan's own, off this week's
# board (2026-11-18) -- the names that prompted the rule. The rest are names
# commonly used for more than one gender in the US, or names where the usual
# reading depends on a spelling difference too small to rely on (Jean, Shawn,
# Noel, Rene, Jaime).
#
# WHEN IN DOUBT, ADD TO THIS LIST. A name here costs one typed cell. A wrong
# name on a clear list costs a corrected payroll record, and only if somebody
# notices.
AMBIGUOUS = frozenset("""
ayodele marquette jovani penina sumera toni carmen

adrian ai akira alex alexis ali alva amari an andrea angel anh ariel armani
ash ashton aubrey august austen avery azariah
bao bay bellamy bergen billie blair blake bobbie brett briar brook brooke
cache cameron campbell carey carmen carol casey cassidy chandler charlie
chris cleo clare cody corey courtney cruz cypress
dakota dale dana dani danny darcy darian deandre dev devon dior dominique
drew dusty dylan
eden elliot elliott ellis emerson emory erin esme evan everest
finley flynn frances francis
gabriel gael gale georgie gray grey guadalupe
hadley haleem harley harlow harper haven hayden hollis hunter
indigo ira isa ivory
jackie jade jaime jamie jan jas jay jean jess jessie jo jody jordan jorden
jory joss jules justice
kai kam kamari karter kasey kayden keegan kelly kelsey kendall kennedy kerry
kim kiran kit kori kris kyle
lane lee leigh lennon lennox leslie lin london lonnie loren lou lucky lumen
lyric
mackenzie madison marion marley marlo mel merle micah michel mika milan
monroe montana morgan murphy
nat navy neo nevaeh nico nikita noel noor north nour
oakley ocean ode ollie onyx oriel
paige paris parker pat patrice payton peyton phoenix piper pres price
quincy quinn
rae raf rain raven ray reagan reed reese regan remy rene reno riley ripley
river roan robin rory rowan royal rudy run rune ryan
sage sal salem sam sandy sasha saxon scout shae shan shane shannon shawn
shay shea shiloh shin sidney skye skyler sloan sol sonny stevie storm sunny
sutton swan sydney
tai tal tamar tanner tate taylor teagan terry tobi tony tory tracy trinity
tru tyler
val valentine vernon
wes west whitney wren wynn
yael yuki
zane zion
""".split())

# --- NAMES THAT ARE CLEAR ----------------------------------------------------
# Common US first names, including the nicknames people actually write on a
# form. Kept deliberately narrower than "every name we could find": the point
# is that anything here can be filled in without a person checking it.
_FEMALE_WORDS = frozenset("""
aalya ailonnie alena asia emilee jazmyne kamila macie tierra abby abigail ada adriana agnes aisha alana alexandra alexandria alice alicia
alina alison allison alma alyssa amanda amber amelia amy ana anastasia angela
angelica angelina anita ann anna annabelle anne annette annie antoinette
april arianna ariana ashley aurora autumn ava
barbara beatrice becky belinda bernadette bertha bessie beth bethany betty
beverly bianca blanca bonnie brandi brenda brianna bridget brittany brooklyn
camila candace candice cara caridad carla carlotta carmela carolina caroline
carolyn cassandra catalina catherine cathy cecilia celeste celia chandra
charlene charlotte chelsea cheryl chloe christina christine cindy claire
clara claudia colleen connie constance consuelo cora corina courtney cristina
crystal cynthia
daisy dana danielle daniela daphne darlene dawn deanna debbie deborah debra
deirdre delia delilah denise destiny diana diane dianne dolores dominga dora
doreen doris dorothy
ebony edith edna eileen elaine eleanor elena eliana elisa elisabeth elise
eliza elizabeth ella ellen eloise elsa elsie emilia emily emma erica erika
esmeralda esperanza estella esther ethel eugenia eunice eva evangelina eve
evelyn
faith fatima felicia fernanda fiona flora florence frances francesca
freda frida
gabriela gabriella gail genesis genevieve georgia georgina geraldine gina
ginger giselle gladys glenda gloria grace gracie greta gretchen guadalupe
gwen gwendolyn
hailey haley hannah harriet hazel heather heidi helen helena henrietta hilda
hillary holly hope
ida imani imelda ingrid irene iris irma isabel isabella isabelle ivy
jackeline jaclyn jacqueline jada jade jamila jan jane janelle janet janice
janie jasmine jayla jean jeanette jeanne jenna jennifer jenny jessica jewel
jill joan joann joanna joanne jocelyn jodi johanna josefina josephine joy
joyce juanita judith judy julia juliana julie juliet june justine
kara karen karina karla kate katelyn katherine kathleen kathryn kathy katie
katrina kaya kayla keisha kelsie kendra kerri khadija kiara kim kimberly
kirsten krista kristen kristin kristina kristy krystal
lacey laila lakeisha lana lara larissa latasha latoya laura laurel lauren
laurie leah leila lena leona leonor leslie leticia lydia lila lilia lillian
lily linda lindsay lindsey lisa liliana lizbeth lois lola lora loretta lori
lorena lorraine louisa louise lucia lucille lucy luisa lupe lydia lyla lynn
mabel madeline madeleine madelyn maggie magdalena maite mallory mamie mara
marcela marcia margaret margarita marguerite maria mariah mariana maribel
maricela marie mariela marilyn marina marion marisa marisol maritza marjorie
marlene marsha martha martina mary maryann matilda maud maureen maxine maya
meagan megan meghan melanie melba melinda melissa melody mercedes meredith
mia micaela michaela michele michelle mildred milagros millie mindy minerva
miranda miriam misty mollie molly mona monica monique morgan muriel myra
myrtle
nadia nadine nancy naomi natalia natalie natasha nayeli nell nena nicole
nikki nina noelia noemi nora norma
octavia odessa ofelia olga olivia opal ophelia
paige paloma pamela paola patricia patsy paula paulette pauline pearl peggy
penelope penny perla petra phoebe phyllis polly priscilla
rachel ramona raquel rebecca rebekah regina renata rene renee reyna rhoda
rhonda rita roberta robyn rochelle rocio romina ronda rosa rosalie rosalind
rosaura rose rosemarie rosemary rosie roxana roxanne ruby ruth
sabrina sadie salma samantha sandra sara sarah savannah selena selina serena
shakira shannon shari sharon shawna sheila shelby shelly sheri sherri sherry
shirley sierra silvia simone sofia sonia sonya sophia sophie stacey stacy
stella stephanie sue susan susana suzanne sybil sylvia
tabitha talia tamara tammy tania tanya tara tasha tatiana teresa teri tess
thelma theresa tiana tiffany tina tonya tracey tracy tricia trina trisha
ursula
valentina valeria valerie vanessa velma vera verna veronica vicki vickie
vicky victoria viola violet virginia vivian viviana
wanda wendy whitney wilma winifred
xiomara
yadira yarely yasmin yesenia yolanda yvette yvonne
zaida zara zelda zoe zoey
""".split())

_MALE_WORDS = frozenset("""
javion kaylon landen tyron aaron abdul abel abraham adam adolfo adrianne agustin ahmad ahmed alan
albert alberto aldo alejandro alexander alfonso alfred alfredo algemar ali
allan allen alonzo alphonso alvaro alvin amos anderson andre andreas andres
andrew andy angelo anibal anthony antoine anton antonio archie ariel arjun
armando arnold arthur arturo asher aubrey august aurelio
barry bart basil beau ben benjamin benito bennie bernard bernardo bert
bilal bill billy blaine bob bobby boris brad bradley brady brandon brant
brendan brennan brent brett brian bruce bruno bryan bryant bryce buddy byron
caleb calvin camilo carl carlos carlton carson carter cary cecil cedric
cesar chad chance charles chase chester chris christian christopher clarence
clark claude clay clayton cleveland clifford clifton clint clinton clyde
cody colby cole colin collin colten colton conor conrad constantine cooper
cornelius cortez craig cristian cristobal curtis cyrus
dale dallas dalton damian damien damon dan dana dane daniel dante darius
darnell darrell darren darrin darryl darwin daryl dave david davis dean
deandre dedrick delbert demetrius denis dennis denny derek derrick desmond
devin devon dewayne dexter diego dimitri dion dominic dominick don donald
donnie donovan dorian doug douglas doyle drew duane dudley duncan dustin
dwayne dwight
earl earnest ed eddie edgar edgardo edison edmund edmundo eduardo edward
edwin efrain efren elbert eli elias elijah eliseo elliot ellis elmer eloy
elton elvin elvis emanuel emiliano emilio emmanuel emmett enoch enrique
ephraim eric erick erik ernest ernesto errol ervin esteban ethan eugene
eusebio evan everett ezekiel ezequiel ezra
fabian federico felipe felix ferdinand fermin fernando fidel filiberto
floyd forrest francesco francisco frank frankie franklin fred freddie
frederick fredrick
gabriel gage galen garrett garry garth gary gaspar gavin gene genaro geoffrey
george gerald gerardo gerard german gilbert gilberto giles gino giovanni
glen glenn gonzalo gordon graham grant granville greg gregg gregorio gregory
griffin guadalupe guillermo gus gustavo guy
hal hamilton hank hans harlan harold harris harrison harry harvey hasani
hassan hayden heath hector henry herbert heriberto herman hernan hilario
hiram hobert hollis homer horace horacio howard hubert hugh hugo humberto
hunter hussein
ian ignacio ike ira irvin irving isaac isaiah isiah ismael israel issac
ivan
jack jackson jacob jacques jaden jaime jairo jake jamaal jamal jamel james
jamie jamison jan jared jarod jarrett jarvis jason jasper javier jay jayden
jean jed jeff jefferson jeffery jeffrey jerald jeremiah jeremy jermaine
jerome jerrell jerry jess jesse jessie jesus jim jimmie jimmy joan joaquin
joe joel joey johan john johnathan johnnie johnny jon jonah jonas jonathan
jordan jorge jose joseph josh joshua josiah jovan juan judson jules julian
julio julius junior justin
kai kaleb kareem karl kasey keaton keenan keith kelvin ken kendrick kenneth
kenny kent kenton kerry keven kevin khalid khalil kieran king kirby kirk
knute korey kory kris kurt kurtis kyle
lamar lamont lance landon lane larry laurence lawerence lawrence lazaro
leandro lee leif leland lemuel len lenard leo leon leonard leonardo leonel
leopoldo leroy les lester levi lewis liam lincoln lionel lloyd logan long
lonnie loren lorenzo lou louie louis lowell lucas luciano lucien lucio
ludwig luigi luis luke luther lyle lyman lynn
mac mack major malachi malcolm malik manuel marc marcel marcelino marcello
marcos marcus margarito mariano mario mark markus marlin marlon marquis
marshall martin marty marvin mason mateo mathew matt matthew maurice mauricio
mauro max maxamad maximilian maxwell maynard mckinley melvin merle merlin
mervin micah michael micheal miguel mike milan miles milford millard milo
milton mitch mitchell mohamed mohammad mohammed moises monroe monte montgomery
morgan morris moses moshe murray myles myron
napoleon nathan nathaniel neal ned neil nelson nestor nicholas nick nicolas
nigel noah noe nolan norbert norman norris
octavio odell odis olen olin oliver ollie omar omer oren orlando orval
oscar osvaldo oswaldo otis otto owen
pablo paris parker pasquale pat patricio patrick paul pedro percy perry
pete peter phil philip phillip pierre porfirio porter preston prince
quentin quincy quinn quinton
rafael raleigh ralph ramiro ramon randal randall randolph randy raphael
raul ray raymond raymundo reed refugio reggie reginald reid reinaldo rene
renato reuben rex reyes reynaldo rhett ricardo richard richie rick rickey
ricky rico rigoberto riley rob robert roberto robin rocco rocky rod roderick
rodger rodney rodolfo rodrigo rogelio roger roland rolando rolf roman romeo
ron ronald ronnie roosevelt rory roscoe ross rowan roy royal royce ruben
rudolph rudy rufus rupert russell rusty rutherford ryan
sal salvador salvatore sam sameer sammie sammy samuel sanford santiago
santos saul scot scott sean sebastian sergio seth seymour shad shane shannon
shaun shawn shelby sheldon sherman shon sid sidney silas simon sol solomon
sonny spencer stan stanford stanley stefan stephan stephen sterling steve
steven stewart stuart sung sydney sylvester
tad tanner tarik taylor ted teddy terence terrance terrell terrence terry
thaddeus theo theodore thomas thurman tim timmy timothy titus tobias toby
todd tom tomas tommie tommy tony trace tracy travis tre trent trenton
trevor trey tristan troy tuan ty tyler tyree tyrell tyrone tyson
ulises ulysses urban uriel
val valentin van vance vaughn vern vernon vicente victor vince vincent
vincenzo virgil vito
wade waldo wallace walter ward warner warren waylon wayne weldon wendell
werner wes wesley weston wilbert wilbur wiley wilford wilfred wilfredo
will willard william willie willis wilmer wilson wilton winfred winston
woodrow wyatt
xavier
yahir yoel young yusuf
zachariah zachary zachery zane zeb zachary
""".split())


# --- THE INVARIANT, ENFORCED RATHER THAN REMEMBERED --------------------------
# The two lists above are hand-written and will be edited by people, so the
# rules about them are applied here instead of trusted:
#
#   * a name in AMBIGUOUS is removed from BOTH clear lists. Adding "Jordan" to
#     a clear list by mistake therefore changes nothing, which is the point --
#     the safe answer wins without anybody having to notice the clash.
#   * a name that ended up on BOTH clear lists is not a clear name at all. It
#     is moved into the ambiguous set rather than resolved by whichever
#     frozenset happens to be checked first. Dana, Jean, Morgan, Shannon and
#     Tracy all arrived this way, and every one of them really is used both
#     ways.
#
# So the lists below are what the code actually consults, and AMBIGUOUS_ALL is
# what a reader should look at to answer "would this name be guessed?".
_BOTH = _FEMALE_WORDS & _MALE_WORDS
AMBIGUOUS_ALL = frozenset(AMBIGUOUS | _BOTH)
CLEAR_FEMALE = frozenset(_FEMALE_WORDS - AMBIGUOUS_ALL)
CLEAR_MALE = frozenset(_MALE_WORDS - AMBIGUOUS_ALL)


def _normalise(raw: str) -> str:
    """'Mary-Jane O'Neil' -> 'mary'. '' when there is nothing to read.

    The FIRST token only, and accents folded: a form carries "José" and a
    board carries "Jose", and they are the same person. Hyphenated and
    apostrophed names split on the punctuation, because the leading part is
    the one people answer to.
    """
    text = unicodedata.normalize("NFKD", str(raw or ""))
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower().strip()
    parts = [p for p in re.split(r"[^a-z]+", text) if p]
    return parts[0] if parts else ""


def suggest(first_name: str) -> str:
    """FEMALE, MALE, or "" when it is not clear. "" is the usual answer.

    Ambiguity wins outright and is checked first, so a name someone later
    adds to a clear list by mistake still comes back blank -- and a name that
    ends up on both clear lists is treated as ambiguous rather than letting
    the order of two frozensets decide a payroll record. See AMBIGUOUS_ALL.
    """
    key = _normalise(first_name)
    if not key or key in AMBIGUOUS_ALL:
        return ""
    if key in CLEAR_FEMALE:
        return FEMALE
    if key in CLEAR_MALE:
        return MALE
    return ""


def plan(rows: Sequence[Dict]) -> List[Dict]:
    """[{row, name, first, suggest}] -- only blanks we can fill confidently.

    Three ways to be left out, and all three are silent on purpose: a cell
    that already holds anything (never overwrite), a name that is not clear
    (leave it to the admin), and a row with no first name at all.

    Takes the board rows that `board.for_week` returns, so this knows nothing
    about sheets and can be tested on dictionaries.
    """
    out: List[Dict] = []
    for r in rows:
        if str(r.get(B.GENDER) or "").strip():
            continue                       # rule 3: never overwrite
        first = str(r.get("Name") or "").strip()
        guess = suggest(first)
        if not guess:
            continue                       # rules 1 and 2: blank, not a guess
        out.append({
            "row": r.get("_row") or r.get("row"),
            "name": ("%s %s" % (first, r.get("Last Name") or "")).strip(),
            "first": first,
            "suggest": guess,
        })
    return out


def _why_blank(first: str) -> str:
    """Why this name got no suggestion, in words an admin can act on.

    THE TWO REASONS ARE DIFFERENT AND MUST READ DIFFERENTLY. "Jordan is used
    both ways" is a decision we made and will not revisit. "Emilee is not on
    the list" is a gap, and whoever reads it may well be able to close it. The
    first wording on both said everybody was ambiguous, which told an admin
    that a name we had simply never seen was a name nobody should guess --
    untrue, and it hides the gap.
    """
    if not str(first or "").strip():
        return "no first name on the row"
    key = _normalise(first)
    if key in AMBIGUOUS_ALL:
        return "%s is used both ways, so nobody should guess" % first
    return "%s isn't on the list of names we read as clear" % first


def unclear(rows: Sequence[Dict]) -> List[Dict]:
    """The blanks this will NOT fill, so a run can say who still needs a person.

    The counterpart to `plan`, and the more important half of the report: the
    number that matters to an admin is how many cells they still have to type,
    not how many were filled for them.
    """
    out: List[Dict] = []
    for r in rows:
        if str(r.get(B.GENDER) or "").strip():
            continue
        first = str(r.get("Name") or "").strip()
        if suggest(first):
            continue
        out.append({"row": r.get("_row") or r.get("row"),
                    "name": ("%s %s" % (first, r.get("Last Name") or "")).strip(),
                    "first": first,
                    "why": _why_blank(first)})
    return out


def wanted(rows: Sequence[Dict]) -> Dict[str, str]:
    """{full name: Female/Male} for `by_hand.write`.

    Deliberately routed through the existing writer rather than a new one:
    it already refuses to write a name the board does not answer to, and
    already writes only what differs.
    """
    return {p["name"]: p["suggest"] for p in plan(rows)}


# --- Putting the suggestions on the board ------------------------------------

def fill(office_key: str, week_start=None, *, dry_run: bool = False,
         log=print) -> int:
    """Pre-fill the clear blanks for one office's week. Returns how many.

    The write itself goes through `by_hand.write`, which already refuses a
    value Apex's dropdown would not match and already writes only what
    differs. What this adds is the tint, applied AFTER the write so a failed
    write cannot leave a coloured cell claiming a value that is not there.

    It always reports the cells it did NOT fill. That is the half an admin
    acts on, and a run that printed only its own successes would read as
    "gender: done" on a week where seven people still need typing.
    """
    import datetime as dt

    from automations.icd_onboarding import by_hand as BH
    from automations.icd_onboarding import fillers as F
    from automations.icd_onboarding import sheet as S

    ws = S.open_board(F.workbook_for(office_key), create=False)
    if ws is None:
        log("  no onboarding board for %s yet." % office_key)
        return 0
    grid = ws.get_all_values()
    cols = S.layout(grid)
    if B.GENDER not in cols:
        raise RuntimeError(
            "the board has no %r column. If it was renamed, rename it in "
            "board.py too -- this never guesses at a position." % B.GENDER)
    all_rows = S.rows_of(grid)
    week = week_start or B.week_start_of(dt.date.today())
    mine = B.for_week(all_rows, week)

    todo = plan(mine)
    still = unclear(mine)
    for p_ in todo:
        log("  suggest  %-28s %s" % (p_["name"], p_["suggest"]))
    if still:
        log("  %d still need a person to type them:" % len(still))
        for p_ in still:
            log("     %-28s %s" % (p_["name"], p_["why"]))
    if not todo:
        log("  nothing clear enough to suggest.")
        return 0
    if dry_run:
        log("  --dry-run: nothing written.")
        # The COUNT IT WOULD FILL, not 0. A preview that ends "0 cells would
        # be filled" under a list of eleven suggestions reads as "this does
        # nothing", and the next person turns it off.
        return len(todo)

    n = BH.write(office_key, B.GENDER, wanted(mine), week, log=log)
    if not n:
        return 0

    # The tint is the whole point: it is what lets an admin see at a glance
    # which of these answers nobody has checked.
    a1 = S._a1(cols[B.GENDER] + 1)
    want_names = {p_["name"] for p_ in todo}
    cells = ["%s%d" % (a1, S.FIRST_DATA_ROW + i)
             for i, r in enumerate(all_rows)
             if ("%s %s" % (r.get("Name", ""), r.get("Last Name", ""))).strip()
             in want_names]
    if cells:
        try:
            ws.format(cells, {"backgroundColor": B.SUGGESTED})
        except Exception as exc:                            # noqa: BLE001
            # A missing tint is cosmetic; a half-written week is not. Say so
            # and keep the values -- the admin has a correct cell that merely
            # does not look provisional.
            log("  (wrote the values, but couldn't tint them: %s)" % exc)
    return n


def main(argv=None) -> int:
    import argparse
    import datetime as dt

    ap = argparse.ArgumentParser(
        description="Pre-fill Gender on an onboarding board, where the first "
                    "name makes it clear. Never overwrites a typed answer.")
    ap.add_argument("--office", default="",
                    help="the office key, as in office-mapping.json")
    ap.add_argument("--week", default="",
                    help="the Monday to fill, YYYY-MM-DD. Default: this week.")
    ap.add_argument("--dry-run", action="store_true",
                    help="print what it would fill and change nothing.")
    ap.add_argument("--name", default="",
                    help="just show what this one first name would suggest, "
                         "and touch no board at all.")
    args = ap.parse_args(argv)

    if args.name:
        got = suggest(args.name)
        print("%s -> %s" % (args.name, got or
                            "(blank -- not clear enough to suggest)"))
        return 0

    if not args.office:
        print("Which office? Pass --office <key>, or --name <first name> to "
              "just see what one name would suggest.")
        return 2

    week = None
    if args.week:
        try:
            week = dt.date.fromisoformat(args.week)
        except ValueError:
            print("--week wants YYYY-MM-DD, e.g. 2026-11-23.")
            return 2
    n = fill(args.office, week, dry_run=args.dry_run)
    print("%d cell(s) %s." % (n, "would be filled" if args.dry_run
                              else "filled"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
