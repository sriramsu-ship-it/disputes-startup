"""Obviously-synthetic vocabulary. Invented names and places only.

Surnames are invented words, the state code ZZ is not a USPS code, ZIP codes in
000xx are unassigned, area code 000 is invalid in the NANP, and SSN-shaped
values use area 9xx with group 00, which SSA never assigns (verified, see
synthgen/pii_guard.py). Organisations are labelled (SYNTHETIC).
"""

FIRST_NAMES = [
    "Avery", "Jordan", "Riley", "Casey", "Morgan", "Quinn", "Rowan", "Skyler",
    "Harper", "Emerson", "Finley", "Reese", "Dakota", "Sage", "Parker", "Tatum",
]
SURNAMES = [
    "Synthwood", "Fixturo", "Mockbury", "Testcombe", "Dummerlin", "Placeholt",
    "Fauxley", "Simulani", "Genwright", "Seedmore", "Stubridge", "Fabrikov",
]
STREETS = ["Synthetic Ave", "Fixture Ln", "Placeholder Rd", "Mockingbird Test Way", "Sample Ct"]
CITIES = ["Fixtureville", "Testburg", "Mockton", "Sampleford"]
STATE = "ZZ"
FURNISHER = "Example Fintech Lender (SYNTHETIC)"
CONSUMER_BANK = "Example Consumer Bank (SYNTHETIC)"
CRAS = ["SYNTH-CRA-1", "SYNTH-CRA-2", "SYNTH-CRA-3"]
PRODUCTS = ["UNSECURED_INSTALLMENT", "CREDIT_CARD"]

MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July",
               "August", "September", "October", "November", "December"]
MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
