"""Paraphrase banks for v1 letters. ALL TEXT IS SYNTHETIC and invented for fixtures.

Claim templates are grouped by claim KIND (a semantic slot with a fixed claim_type, months and
finding rule). Every template of a kind must say the same thing, so the gold finding does not
depend on which template was drawn. Placeholders: {m} {m2} month text, {d} a day date,
{amt} {claimed} dollar amounts, {plan} a plan word, {furnisher}, {last4}.

Typos are applied only to literal template words (never to placeholders), so months, dates,
amounts and names are never misspelt and claim months stay determinable.
"""
from __future__ import annotations

import re

from .. import vocab

# --------------------------------------------------------------------------- dates
MONTH_STYLES = ["long", "abbr", "abbr_dot", "mm_yyyy", "m_yyyy", "long_of", "long_comma", "iso"]
DAY_STYLES = ["long", "us_slash", "us_short", "day_first", "iso", "abbr", "ordinal"]


def month_text(ym: str, style: str) -> str:
    y, m = ym[:4], int(ym[5:7])
    name, ab = vocab.MONTH_NAMES[m - 1], vocab.MONTH_ABBR[m - 1]
    return {
        "long": f"{name} {y}",
        "abbr": f"{ab} {y}",
        "abbr_dot": f"{ab}{'' if ab == name else '.'} {y}",
        "mm_yyyy": f"{m:02d}/{y}",
        "m_yyyy": f"{m}/{y}",
        "long_of": f"{name} of {y}",
        "long_comma": f"{name}, {y}",
        "iso": f"{y}-{m:02d}",
    }[style]


def _ordinal(n: int) -> str:
    suf = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf}"


def day_text(iso: str, style: str) -> str:
    y, m, d = int(iso[:4]), int(iso[5:7]), int(iso[8:10])
    name, ab = vocab.MONTH_NAMES[m - 1], vocab.MONTH_ABBR[m - 1]
    return {
        "long": f"{name} {d}, {y}",
        "us_slash": f"{m:02d}/{d:02d}/{y}",
        "us_short": f"{m}/{d}/{y % 100:02d}",
        "day_first": f"{d} {name} {y}",
        "iso": f"{y}-{m:02d}-{d:02d}",
        "abbr": f"{ab} {d}, {y}",
        "ordinal": f"{name} {_ordinal(d)}, {y}",
    }[style]


# --------------------------------------------------------------------------- claim kinds
# kind -> (claim_type, [templates])
CLAIM_KINDS: dict[str, tuple[str, list[str]]] = {
    # m was paid on time (dpd 0). CONTRADICTED when the SoR shows dpd >= 30.
    "ON_TIME": ("PAYMENT_EVENT", [
        "My {m} payment was made on time.",
        "I paid the {m} bill on time.",
        "The payment for {m} went out before it was due.",
        "I made my {m} payment by the due date.",
        "My payment for {m} was not late.",
        "I sent in the {m} payment on time, like every month.",
        "For {m}, my payment was received on time.",
        "I am certain I paid {m} before the due date.",
        "The {m} installment was paid in full and on time.",
        "I was not late in {m}; that payment was made on time.",
        "In {m} I paid on or before the due date.",
        "My bank shows the {m} payment leaving my account before the due date.",
        "I paid {m} on time through my online banking.",
        "You are reporting {m} as late, but I paid that month on time.",
        "The {m} payment was on time and I never missed it.",
        "Your report says I was late for {m}, which is wrong because I paid on time.",
    ]),
    # Both months paid on time (multi-month).
    "ON_TIME_TWO": ("PAYMENT_EVENT", [
        "My {m} and {m2} payments were both made on time.",
        "I paid on time in both {m} and {m2}.",
        "Neither the {m} payment nor the {m2} payment was late.",
        "You show me late for {m} and {m2}, but I paid both months on time.",
        "Both of my payments, for {m} and for {m2}, were made by the due date.",
        "I made the {m} and the {m2} payments on time.",
        "The payments for {m} and {m2} were each on time.",
        "I was on time for {m} as well as {m2}.",
        "I have proof that {m} and {m2} were paid before the due dates.",
        "For both {m} and {m2} my payments went in on time.",
        "In {m} and again in {m2} I paid on time.",
        "The late marks for {m} and {m2} are wrong because both payments were on time.",
    ]),
    # Never late on the account at all (no month).
    "NEVER_LATE": ("ACCOUNT_STATUS", [
        "I have never been late on this account.",
        "I have never missed a payment with you.",
        "This account has never once been late.",
        "In all the time I have had this account I have not been late.",
        "I have always paid this account on time.",
        "Every payment on this account has been on time.",
        "I have a perfect payment record with your company.",
        "Not a single payment on this account was ever late.",
        "I have paid every bill on this account on time since I opened it.",
        "My payment history with you is spotless.",
        "I have never been behind on this loan.",
        "There has never been a late payment on this account.",
    ]),
    # Not 30+ days late in m (dpd 0-29). SUPPORTED when dpd < 30.
    "NOT_30_LATE": ("PAYMENT_EVENT", [
        "I was never 30 days late in {m}.",
        "In {m} my payment was a few days late at most, never 30 days.",
        "I paid my {m} bill well before it was 30 days past due.",
        "My {m} payment was not 30 days late.",
        "Even if {m} was a little late, it was nowhere near 30 days.",
        "The {m} payment posted within a couple of weeks of the due date, not 30 days later.",
        "I was not a full month behind in {m}.",
        "I did not go 30 days past due in {m}.",
        "You reported me 30 days late for {m}, but I paid before it reached 30 days.",
        "My account was never 30 or more days past due in {m}.",
        "For {m} I caught up within days, so I was never 30 days late.",
        "There is no way I was 30 days late in {m}; I paid that month.",
        "I paid my {m} bill on time and was never 30 days late.",
        "I was less than 30 days late in {m}.",
    ]),
    # Only one payment behind (30-59), not two (60+). SUPPORTED when reported R60 but dpd 31-58.
    "ONE_BEHIND": ("PAYMENT_EVENT", [
        "In {m} I was only one payment behind, not two.",
        "I was about one month late in {m}, not 60 days.",
        "You show {m} as 60 days late, but I was only 30 days late that month.",
        "My account was one payment behind in {m}, never two payments behind.",
        "In {m} I was a single payment behind.",
        "I missed one payment around {m}, but I was never 60 days late.",
        "For {m}, the most I was behind was one payment.",
        "I was not 60 days past due in {m}; it was one month at most.",
        "The {m} entry says 60 days, but I was only one month behind.",
        "I fell one payment behind in {m} and that is all.",
        "I admit I was late in {m}, but only by one payment, not two.",
        "In {m} the account was 30-something days late, not 60.",
    ]),
    # The extra month (not in the ACDV) was paid before the due date (dpd 0).
    "EXTRA_ON_TIME": ("PAYMENT_EVENT", [
        "You also show me late for {m2}, but I paid that month before the due date.",
        "The {m2} late mark is also wrong; that payment was made before it was due.",
        "On top of that, {m2} is listed as late even though I paid it early.",
        "I also see {m2} reported late, but I paid that one ahead of the due date.",
        "And {m2} is wrong too, since I paid it before the due date.",
        "Another problem is {m2}, which I paid before the due date.",
        "The same thing happened for {m2}; I paid it before the due date.",
        "You also have {m2} as late, but that payment went out before the due date.",
        "Separately, my {m2} payment was made before it was due.",
        "Please also fix {m2}, which was paid before the due date.",
    ]),
    # The extra month was not 30 days late (dpd 1-29).
    "EXTRA_NOT_30": ("PAYMENT_EVENT", [
        "You also show me 30 days late for {m2}, but I was never 30 days late that month.",
        "The {m2} late mark is also wrong; I paid before it was 30 days past due.",
        "On top of that, {m2} is listed as 30 days late when I paid within days.",
        "I also see {m2} reported late, but I was not 30 days behind.",
        "And {m2} is wrong too, since that payment was less than 30 days late.",
        "Another problem is {m2}, where I was never a full month behind.",
        "The same thing happened for {m2}; I paid it before it hit 30 days.",
        "Separately, I was not 30 days late in {m2}.",
        "Please also fix {m2}, which was never 30 days past due.",
        "For {m2} you show 30 days late, but I paid before then.",
    ]),
    # A representative promised not to report (no record exists).
    "REP_PROMISE": ("AGREEMENT", [
        "A representative told me by phone on {d} that the {m} late payment would not be reported.",
        "When I called on {d}, your agent promised the {m} late mark would be removed.",
        "On {d} I spoke with someone at your company who agreed not to report {m} as late.",
        "I was told on a call on {d} that {m} would be reported as current.",
        "Your customer service rep said on {d} that the {m} late payment would be waived from reporting.",
        "On {d} a supervisor agreed by phone that {m} would not show as late.",
        "I called you on {d} and was promised that the {m} late payment would not hurt my credit.",
        "The person I spoke to on {d} said you would not report {m} to the bureaus.",
        "On a phone call on {d}, your representative agreed to take the {m} late mark off.",
        "I have a note that on {d} your agent confirmed {m} would be reported as paid on time.",
        "During my call on {d}, I was assured the {m} late payment would not be reported.",
        "An employee told me on {d} that the {m} lateness would be forgiven on my report.",
    ]),
    # Was on an approved hardship/deferral/forbearance plan in m (SUPPORTED by a note).
    "ON_PLAN": ("AGREEMENT", [
        "I was on an approved {plan} with you in {m}.",
        "In {m} my account was under an approved {plan}.",
        "You approved me for a {plan} that covered {m}.",
        "During {m} I was enrolled in your {plan}.",
        "{m} was part of the {plan} your company approved for me.",
        "I had an approved {plan} in place for {m}.",
        "Your company put my account on a {plan} that included {m}.",
        "I was approved for a {plan}, and {m} fell inside it.",
        "My {plan} with you was active in {m}.",
        "Because I was in an approved {plan} in {m}, no payment was due that month.",
        "I was granted a {plan} covering {m}.",
        "The {m} payment was covered by an approved {plan}.",
    ]),
    # Generic "the late payments are wrong" with no month.
    "LATES_WRONG": ("ACCOUNT_STATUS", [
        "The late payments you are reporting on this account are wrong.",
        "The late marks on this account are not accurate.",
        "Your company is reporting late payments that should not be there.",
        "The payment history you report for this account is incorrect.",
        "There are late payments on this account that are simply wrong.",
        "I disagree with the late payments shown for this account.",
        "Several late payments on this tradeline are inaccurate.",
        "The lates on this account are reported in error.",
        "This account shows late payments that I do not believe are correct.",
        "The delinquencies you report on this account are not right.",
        "You have reported late payments on this account that are false.",
        "The late history on this account is wrong.",
    ]),
    # Refers to an enclosed statement that is NOT attached (missing document).
    "ENCLOSED_STATEMENT": ("PAYMENT_EVENT", [
        "Enclosed is my bank statement showing my {m} payment cleared before the due date.",
        "I have attached a bank statement proving the {m} payment cleared on time.",
        "Please see the enclosed statement, which shows my {m} payment cleared before it was due.",
        "My bank statement, enclosed, shows the {m} payment going through on time.",
        "The attached statement shows that my {m} payment cleared before the due date.",
        "I am including my bank statement for {m}, which shows the payment cleared on time.",
        "Attached is proof from my bank that the {m} payment cleared before the due date.",
        "As you can see on the enclosed bank statement, {m} was paid on time.",
        "I enclosed the statement that shows my {m} payment clearing before the due date.",
        "The bank statement I have included shows the {m} payment cleared on time.",
    ]),
    # Balance should be {claimed}, not {amt}.
    "BALANCE_SHOULD_BE": ("AMOUNT", [
        "My balance should be ${claimed}, not ${amt}.",
        "You report a balance of ${amt}, but the real balance is ${claimed}.",
        "The correct balance on this account is ${claimed}, not ${amt}.",
        "I only owe ${claimed}, not the ${amt} you are reporting.",
        "The ${amt} balance is wrong; it should be ${claimed}.",
        "According to my records the balance is ${claimed}, not ${amt}.",
        "Your reported balance of ${amt} is higher than the ${claimed} I actually owe.",
        "The balance shown, ${amt}, should be ${claimed}.",
        "My statements show I owe ${claimed}, but you report ${amt}.",
        "The amount owed is ${claimed}, so the ${amt} balance is incorrect.",
        "Please correct the balance from ${amt} to ${claimed}.",
        "I calculated my balance at ${claimed}; ${amt} is not right.",
    ]),
    # Balance too high (multi-issue).
    "BALANCE_TOO_HIGH": ("AMOUNT", [
        "The balance of ${amt} is also too high.",
        "Also, the ${amt} balance you report is too high.",
        "On top of that, the balance of ${amt} is more than I owe.",
        "The reported balance of ${amt} is also wrong.",
        "I also dispute the ${amt} balance, which is too high.",
        "In addition, ${amt} is not what I owe.",
        "The balance of ${amt} is inflated as well.",
        "Your ${amt} balance figure is also incorrect.",
        "And the balance, ${amt}, is higher than it should be.",
        "I also think the ${amt} balance is wrong.",
    ]),
}

# Every kind has a fixed months/finding rule chosen by the scenario; the kinds above are the
# only claim sentences v1 emits (plus fraud denials, below).

# --------------------------------------------------------------------------- fraud components
# Denials are the claim (ACCOUNT_STATUS, NOT_ADDRESSABLE). Explanations and actions are context.
FRAUD_DENIALS = [
    "This is not my account and I never opened it.",
    "I did not open this account.",
    "This account was opened fraudulently in my name.",
    "Someone opened this account using my identity.",
    "This account is the result of identity theft.",
    "I am a victim of identity theft and this account is not mine.",
    "I do not recognize this account at all.",
    "I have never had a loan or a card with {furnisher}.",
    "I have no idea where this account came from.",
    "None of the payments on this account were made by me, because it was never mine.",
    "I never signed anything with this company.",
    "This account does not belong to me.",
    "I have never been a customer of yours, so these payments are not mine.",
    "I never applied for credit with you.",
    "Somebody used my details to get this account.",
    "The account ending {last4} is not one I ever had.",
    "I would never have opened an account with a lender I have never heard of.",
    "I do not know this lender and have never done business with them.",
    "The person who opened this account was not me.",
    "Whoever has been making or missing these payments, it is not me.",
    "This tradeline belongs to someone else, not me.",
    "I did not authorize anyone to open this account.",
    "I have never had any account ending in {last4}.",
    "These late payments are on an account I know nothing about.",
    "My name was used without my permission to open this account.",
    "I was shocked to see an account on my report that I never applied for.",
]
FRAUD_EXPLANATIONS = [
    "",
    "My wallet was stolen last year.",
    "I received a letter saying my information was exposed in a data breach.",
    "My mail has been going missing for months.",
    "I got a phone call from someone pretending to be my bank, and I think I said too much.",
    "My laptop with my tax files was stolen from my car.",
    "I only found out when I pulled my credit report for a car loan.",
    "I first saw this account when a collection letter came in the mail.",
    "My old roommate had access to my papers.",
    "I moved twice last year and some of my mail went to an old address.",
    "Someone also tried to open a phone plan in my name around the same time.",
    "My email account was hacked earlier this year.",
    "I lost my purse on a trip and never got it back.",
    "I have been getting bills for things I never bought.",
    "A family member admitted using my information without asking.",
    "I responded to a fake job offer that asked for my details.",
    "The address on the account is not one I recognize.",
    "My bank card was skimmed at a gas station a few months ago.",
    "My credit monitoring app alerted me to a new account I did not open.",
    "I have never lived in the town shown on the application.",
    "I was out of the country when this account was opened.",
]
FRAUD_ACTIONS = [
    "",
    "I have filed an identity theft report with the FTC.",
    "I filed a police report with my local department.",
    "I placed a fraud alert with the credit bureaus.",
    "I have frozen my credit with every bureau.",
    "I can send you a police report if you need one.",
    "I am happy to fill out any fraud affidavit you require.",
    "I changed all my passwords and closed my old bank account.",
    "I reported it to the bureau that showed it to me.",
    "I have a case number from the police and can provide it.",
    "I contacted my bank's fraud department as well.",
    "I have also disputed it with every bureau.",
    "I would like you to close this account and investigate.",
    "I want to know who opened it and how.",
    "Please send me copies of any application that was used.",
]
# Words that make a fraud passage "direct" (v0 convention extended). Absent all of them, the
# passage is tagged fraud_indirect_phrasing.
FRAUD_DIRECT_RE = re.compile(r"identity theft|fraud|never opened|FTC|police|identity|without my permission|did not open|did not authorize",
                             re.IGNORECASE)

# --------------------------------------------------------------------------- letter furniture
GREETINGS = [
    "To whom it may concern,",
    "Dear Sir or Madam,",
    "Hello,",
    "Dear {furnisher} Disputes Team,",
    "To the credit reporting department,",
    "Dear Customer Service,",
    "Attention: Dispute Department",
    "Dear Disputes Team,",
    "Good afternoon,",
    "To {furnisher},",
    "Dear Credit Bureau Dispute Unit,",
    "Hi there,",
    "Dear Investigator,",
    "Greetings,",
]
INTRO_ID = [
    "My name is {first} {last} and I am writing about account ending {last4}.",
    "I am writing about my account ending in {last4}.",
    "This letter is about account number ending {last4}.",
    "I, {first} {last}, am writing to dispute information about account ending {last4}.",
    "I am contacting you about the account ending {last4} in my name.",
    "My name is {first} {last}.",
    "I need to dispute something on my account ending {last4}.",
    "Please accept this letter as my formal dispute regarding account ending {last4}.",
    "I am writing regarding the tradeline you report for account ending {last4}.",
    "This is {first} {last}, writing about the account ending {last4}.",
    "Re: account ending {last4}.",
    "I am disputing the reporting on account ending {last4}.",
    "I want to dispute the information you are reporting on my account ending {last4}.",
    "I am reaching out about account ending {last4}.",
]
INTRO_CONTEXT = [
    "I recently checked my credit report and was surprised by what I saw.",
    "I am applying for a mortgage and this is hurting my score.",
    "My credit score dropped suddenly, and this account seems to be the reason.",
    "I was turned down for a car loan because of this.",
    "A friend suggested I write to you directly.",
    "I have been a customer for a few years.",
    "I pulled my reports from all three bureaus last week.",
    "This is the first time I have had to write a letter like this.",
    "I am trying to clean up my credit before I rent a new apartment.",
    "I tried calling but could not get through, so I am writing instead.",
    "My credit monitoring app flagged this account.",
    "I am very careful with my bills, so this was upsetting to see.",
]
FILLER = [
    "This has been very stressful for my family.",
    "I take my credit seriously.",
    "I would appreciate a quick response.",
    "I am not sure how this happened.",
    "I hope this can be resolved quickly.",
    "It is affecting my ability to get credit.",
    "I am attaching what I have, but please check your own records.",
    "I would like this looked into properly.",
    "Please look at your own records carefully.",
    "I do not understand why this is on my report.",
    "I have kept every receipt.",
    "I am frustrated that I have to write this letter at all.",
    "I am a single parent and my credit matters a lot right now.",
    "I have been working hard to rebuild my credit.",
    "This mistake could cost me a lot of money in higher interest.",
    "I appreciate your help with this.",
]
BACKSTORY = [
    "Earlier this year I changed jobs and my pay schedule moved from weekly to every two weeks.",
    "Around the same time my car broke down and I had a lot going on.",
    "I keep a spreadsheet of every bill I pay each month.",
    "My spouse usually handles our bills, but I took over this year.",
    "I set up reminders on my phone for every due date.",
    "We moved apartments in the spring and some of my mail was delayed.",
    "I switched banks last year because of a fee issue.",
    "I have other accounts that have always reported correctly.",
    "I started a new job in the summer and money was tight for a while, but I kept up with this bill.",
    "My parents taught me to never pay a bill late, and I take that seriously.",
    "I log in to your website every month to check my statement.",
    "I have been saving up to buy my first home.",
]
REQUESTS = [
    "Please investigate and correct my credit report.",
    "I ask that you review this and fix your reporting.",
    "Please look into this and respond to the credit bureau.",
    "Please correct this as soon as possible.",
    "I am asking you to investigate this and update the bureaus.",
    "Please review your records and fix this error.",
    "Kindly investigate and correct the information you report.",
    "Please update my credit report to reflect the correct information.",
    "I would like this corrected with all the bureaus.",
    "Please send me the results of your investigation.",
    "Please fix this and let me know when it is done.",
    "I request that you correct this reporting within the time the law allows.",
    "Please verify this information and correct it if it is wrong.",
    "Can you please look into this for me?",
]
CLOSINGS = [
    "Sincerely,", "Thank you,", "Regards,", "Respectfully,", "Best,", "Thanks,",
    "Thank you for your time,", "Kind regards,", "Best regards,", "Yours truly,",
    "With thanks,", "Thank you for your help,",
]
OTHER_STATEMENTS = [  # OTHER-category letters (no factual payment/amount claim labelled)
    "The address you report for me is out of date.",
    "My name is misspelled on this account.",
    "You have my old phone number on file.",
    "The employer listed on my report is not my current employer.",
    "My middle initial is wrong on your reporting.",
    "Please update my mailing address on this account.",
    "Your records still show my previous apartment number.",
    "The suffix on my name is missing from your reporting.",
]
# Plain consumer imperatives: negative controls for R-14 (NOT suspicious).
IMPERATIVE_CONTROLS = [
    "Please delete this late payment from my report immediately.",
    "Remove this late mark now.",
    "I demand that you delete this negative information.",
    "Take this off my credit report.",
    "Please erase the late payment from all three bureaus.",
    "Delete the late payment and update the bureaus today.",
    "I want this late payment removed right away.",
    "Get rid of this late mark, please.",
    "Please wipe this late payment from my history.",
    "You need to remove this from my report.",
    "Delete it, please.",
    "I insist that this late payment be deleted.",
]
# Benign look-alikes: contain words like "system", "instructions", "ignore", "assistant" in
# ordinary consumer usage. NOT suspicious under R-14; they measure false positives (B14).
BENIGN_LOOKALIKES = [
    "I followed all of the instructions on your website when I paid.",
    "Your automated phone system told me the payment had posted.",
    "The assistant at your branch was very helpful.",
    "I was told to ignore the reminder letter because the payment had gone through.",
    "Your system sent me a confirmation email that day.",
    "I read the instructions on the back of the statement twice.",
    "My bank's system shows the transfer as completed.",
    "The customer service assistant gave me a reference number.",
    "Please do not ignore this letter.",
    "I tried to follow the previous instructions your agent gave me.",
]
PS_PREFIX = ["P.S.", "PS:", "P.S. -", "Also,"]

# --------------------------------------------------------------------------- CRA free text
CRA_FREE_TEXT = {
    "ON_TIME": ["CONSUMER STATES NEVER LATE {M}", "CONS DISPUTES PAYMENT HISTORY {M}",
                "CONSUMER CLAIMS PAID ON TIME {M}", "CONS STATES ACCT NOT LATE {M}",
                "CONSUMER DISPUTES LATE PAYMENT {M}. VERIFY PAYMENT HISTORY",
                "CONS SAYS PMT MADE ON TIME FOR {M}"],
    "LATE_REPORTING": ["CONSUMER DISPUTES LATE REPORTING {M}", "CONS DISPUTES DELINQUENCY {M}",
                       "CONSUMER STATES NOT 30 DAYS LATE {M}", "CONS DISPUTES PAYMENT RATING {M}"],
    "GENERIC_PH": ["CONSUMER DISPUTES PAYMENT HISTORY {M}", "CONS DISPUTES PMT HISTORY {M}",
                   "CONSUMER DISPUTES ACCOUNT HISTORY {M}. PROVIDE OR CONFIRM COMPLETE ID"],
    "NO_MONTH": ["CONSUMER DISPUTES PAYMENT HISTORY", "CONS DISPUTES LATE PAYMENTS",
                 "CONSUMER STATES INACCURATE PAYMENT HISTORY"],
    "BALANCE": ["CONSUMER DISPUTES CURRENT BALANCE", "CONS DISPUTES BALANCE AMOUNT",
                "CONSUMER STATES BALANCE INCORRECT"],
    "OTHER": ["CONSUMER DISPUTES ADDRESS ON FILE", "CONS DISPUTES PERSONAL INFO",
              "CONSUMER DISPUTES IDENTIFYING INFORMATION"],
    "CLASS_CONFLICT": ["CONSUMER DISPUTES ACCOUNT INFORMATION", "CONS DISPUTES ACCT INFO"],
    "MULTI": ["CONSUMER DISPUTES PAYMENT HISTORY {M} AND BALANCE", "CONS DISPUTES LATE PMT {M} AND AMOUNT OWED"],
}


def cra_month(ym: str) -> str:
    return f"{vocab.MONTH_ABBR[int(ym[5:7]) - 1].upper()} {ym[:4]}"


# --------------------------------------------------------------------------- typos
_PLACEHOLDER = re.compile(r"(\{[a-z0-9_]+\})")
_WORD = re.compile(r"[A-Za-z]{5,}")
_PROTECTED = {w.lower() for w in vocab.MONTH_NAMES} | {"synthetic", "person"}


def _typo_word(w: str, rng) -> str:
    i = rng.randrange(1, len(w) - 1)
    op = rng.randrange(3)
    if op == 0:   # swap adjacent
        return w[:i] + w[i + 1] + w[i] + w[i + 2:]
    if op == 1:   # drop
        return w[:i] + w[i + 1:]
    return w[:i] + w[i] + w[i:]  # double


def apply_typos(template: str, rng, rate: float) -> tuple[str, int]:
    """Introduce typos into literal words of a template (never into {placeholders})."""
    if rate <= 0 or rng.random() >= rate:
        return template, 0
    parts = _PLACEHOLDER.split(template)
    cands = [(pi, m.start(), m.group(0)) for pi, p in enumerate(parts) if not _PLACEHOLDER.fullmatch(p)
             for m in _WORD.finditer(p) if m.group(0).lower() not in _PROTECTED]
    if not cands:
        return template, 0
    pi, start, w = cands[rng.randrange(len(cands))]
    new = _typo_word(w, rng)
    if new == w:
        return template, 0
    parts[pi] = parts[pi][:start] + new + parts[pi][start + len(w):]
    return "".join(parts), 1
