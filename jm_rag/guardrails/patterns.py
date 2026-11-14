"""Phrasing lists for the input guard. All matching is on lower-cased text; no LLM is involved.

Ported from the RAG_Capstone reference and adapted to this repo. Each refusal class is a
list of regular expressions; tests/test_guardrails.py checks at least five phrasings per
class. Write intents are anchored to the start of the request or to a request phrase, so
ordinary questions such as "show open work orders for CNC-02" are not refused.
"""
from __future__ import annotations

import re

_PEOPLE = (r"(employees?|workers?|technicians?|operators?|staff|persons?|people|personnel|victims?|"
           r"injured|colleagues?|engineers?|fitters?)")
_VERBS = (r"(change|update|delete|remove|edit|insert|modify|overwrite|erase|rename|reopen|re-open|drop|"
          r"truncate|alter|amend|correct|reduce|increase|raise|lower|decrease|adjust|fix)(?!\s+(?:me|us)\b)")
_DATA_NOUNS = (
    r"(severity|incidents?|work ?orders?|wos?|records?|rows?|tables?|spares?|stock|sops?|machines?|data|"
    r"entr(?:y|ies)|costs?|status|reports?|logs?|database|readings?|capacity|nameplate|min(?:imum)? levels?|"
    r"quantit(?:y|ies)|all|everything|cnc-?\d+|crn-?\d+|[a-z]{2,5}-[a-z]?\d{2}|ir-\d{4}-\d+)"
)
# phrases that turn a sentence into a request addressed to the assistant
_LEAD = (r"(?:^|\b(?:please|kindly|now|just|then|go ahead and|can you|could you|would you|will you|"
         r"i want you to|i want to|i need you to|i need to|i'd like you to|we need to|you must|you should|you need to)\b)\s*")

# --- refusal classes -----------------------------------------------------------
INJECTION = [
    r"ignore (all |any |your |the |these |my )*(previous |prior |above |earlier |system )*(instructions?|rules?|prompts?|guidelines?|restrictions?)",
    r"\bignore (the )?above\b",
    r"disregard (all |any |your |the )*(previous |prior |above |earlier )*(instructions?|rules?|prompts?|guidelines?)",
    r"forget (everything|all|your (instructions?|rules?|training))",
    r"(reveal|show|print|repeat|tell me|display|leak|output) (me )?(your |the )?(system |hidden |secret |initial )?(prompt|instructions?|rules)\b",
    r"\brepeat the (text|words|message) above\b",
    r"system prompt",
    r"^\s*system\s*:",
    r"\byou are now\b",
    r"\byou are dan\b",
    r"\bdeveloper mode\b",
    r"\bjail ?break",
    r"\bdan mode\b|\bdo anything now\b",
    r"pretend (to be|you are|you're)",
    r"act as (an? )?(unrestricted|unfiltered|different|new)",
    r"override (your |the )?(rules|guardrails?|restrictions?)",
    r"without (any )?(restrictions?|filters?|guardrails?)",
    r"\bfollow (any|all|the|those|its|their) instructions? (written|given|contained|found|in)\b",
    r"\b(administrator|admin|developer)\b.{0,30}\b(approved|authori[sz]ed|allowed)\b",
    r"\b(api[- ]?key|password|credentials?|secret key)\b",
    r"\b(env(ironment)? (file|variables?))\b|\.env\b",
    r"\b(run|execute)\b.{0,15}\b(sql|query|queries|shell command|script)\b",
    r"\bselect\s+\*|\bunion\s+select\b|\bfrom\s+(employees|person_names|information_schema)\b",
    r"<\s*script\b",
]

NAME_REQUEST = [
    rf"\b(names?|full name|first name|last name|surname|initials)\b.{{0,60}}\b{_PEOPLE}\b",
    rf"\b{_PEOPLE}('s|s')?\b.{{0,60}}\b(full |first |last )?(names?|initials)\b",
    r"\b(person|personal|employee|staff|worker|injured|people)\s+(columns?|fields?|table|records?)\b|\bevery column\b|\ball (the )?columns\b",
    r"\b(names?|full name|surname|initials) of\b.{0,30}\b(emp\s?-?\d+|everyone|anyone|anybody|those|them|him|her|that (person|man|woman|guy))\b",
    r"\bnames? (of|for) (the )?(emp\s?-?\d+)",
    r"\bwho (is|was|are|were)\b.{0,15}\bemp\s?-?\d+",
    r"\b(tell me|know|say|everything|details?) (about|on|of)\b.{0,10}\bemp\s?-?\d{2,}\b",
    r"\bemp\s?-?\d{3}\b.{0,30}\b(everything|details|information|name|who)\b",
    r"\bwho (was|were|got|is|are)\b.{0,12}\b(injured|hurt|involved|affected|harmed)\b",
    r"\bwho (did|does|caused|causes|is responsible|was responsible|is to blame|was to blame|is at fault|was at fault)\b.{0,40}\b(incident|injur|accident|near.?miss|ir-\d{4}-\d+)",
    r"\b(list|show|give|tell|provide|display)\b.{0,15}\b(all |the |every )?(employees|workers|staff|technicians|personnel|operators)\b",
    r"\bidenti(fy|ty of)\b.{0,30}\b(the )?(injured|worker|employee|technician|operator|victim|person)",
    r"\bwhat('s| is) (his|her|their) name\b",
    r"\bwhich (employee|worker|technician|operator|person|staff) (was|were|got|is|are)\b.{0,20}\b(injured|hurt|involved)",
    r"\b(employees?|person_names?)\s+(table|data)\b|\bemployee table\b",
    r"\bsiapa\b.{0,40}\b(cedera|tercedera|terlibat|pekerja|staf|kakitangan|juruteknik)\b",
    r"\bnama\b.{0,30}\b(pekerja|staf|kakitangan|juruteknik|pengendali)\b",
]

PERSON_RANKING = [
    rf"\b(which|what|who)\b.{{0,5}}\b{_PEOPLE}\b.{{0,45}}\b(most|least|highest|lowest|worst|best|more|fewest|top|largest|biggest|repeat)",
    r"\bwho (has|had|have|got|gets)\b.{0,15}\b(the )?(most|highest|fewest|least|worst|best|more)\b",
    r"\b(worst|best|top|bottom|poorest|weakest)\s+(performer|performing|employee|worker|technician|operator)",
    r"\baccident[- ]prone\b",
    rf"\brank(ing)?\b.{{0,25}}\b{_PEOPLE}\b",
    rf"\b{_PEOPLE}\b.{{0,25}}\b(ranking|league table|leaderboard)\b",
    r"\bwho (is|was) (the )?(most|least|worst|best)\b",
    r"\brepeat offenders?\b",
    rf"\bcompare\b.{{0,25}}\b{_PEOPLE}\b",
]

WRITE_INTENT = [
    rf"^\s*(please\s+|kindly\s+|now\s+|just\s+)?{_VERBS}\b.{{0,60}}\b{_DATA_NOUNS}\b",
    rf"\b(can|could|would|will) you (please )?{_VERBS}\b.{{0,60}}\b{_DATA_NOUNS}\b",
    rf"\b(i want|i need|i'd like|we need|you (must|should|need to)) (you )?(to )?{_VERBS}\b.{{0,60}}\b{_DATA_NOUNS}\b",
    r"^\s*(please\s+|kindly\s+)?(make|put|turn|record|enter)\b.{0,30}\b(incidents?|work ?orders?|severity|stock|minimum|record|status)\b",
    r"\bplease (make|put|turn|record|enter)\b.{0,30}\b(incidents?|work ?orders?|severity|stock|minimum|record|status)\b",
    r"\bset\b.{0,25}\b(severity|status|cost|quantity|stock|level|capacity)\b.{0,35}\bto\b",
    r"^\s*(please\s+)?(close|cancel|approve|reject|assign|reassign|reopen|re-open|void|escalate)\b.{0,15}\b(work ?orders?|wos?|incidents?|tickets?)\b",
    rf"{_LEAD}(mark|close|cancel|approve|reject|assign|reassign|schedule|create|raise|open|log|file|submit|add)\b.{{0,12}}\b(a |an |the |this |that |new )?(work ?orders?|wos?|incidents?|reports?|records?|sops?|spares?|entry|ticket)\b.{{0,30}}\b(as|for|to|on|in|with)\b",
    r"^\s*(please\s+)?(add|create|raise|log|schedule)\b.{0,12}\b(a |an |new )?(work ?orders?|incident|record|entry|ticket|spares?)",
    r"\b(drop|truncate)\s+table\b|\bdelete\s+from\b|\binsert\s+into\b|\bupdate\s+\w+\s+set\b",
    r"\bmark\b.{0,30}\bas (closed|complete|completed|done|resolved)\b",
    rf"{_LEAD}order\b.{{0,12}}\b(spares?|parts?|stock|bearings?|seals?|filters?)\b",
]

# Safety-bypass wording. "SAFETY_NOUN" is what is being bypassed; if it is followed by a
# report-style word ("guard inspection finding") the sentence is about a record, not an action.
_SAFETY_NOUN = (r"(?:safety|interlocks?|loto|lock.?out|tag.?out|permits?|procedures?|guards?|alarms?|"
                r"e-?stops?|emergency stops?|light curtains?|isolation|ppe)")
_RECORD_WORD = (r"(?:inspections?|findings?|reports?|records?|logs?|audits?|history|checks?|status|"
                r"incidents?|observations?|summary|results?)")
SAFETY_BYPASS = [
    rf"\b(?:bypass|bypassing|disable|disabling|defeat|override|overriding|circumvent|tamper with|switch off|turn off)\b"
    rf"(?:\s+\w+){{0,5}}?\s+{_SAFETY_NOUN}\b(?!\s+{_RECORD_WORD}\b)",
    rf"\b(?:ignore|ignoring|skip|skipping|omit|dodge)\b(?:\s+(?:the|a|an|our|this|that|any|all|your))?"
    rf"(?:\s+\w+){{0,2}}?\s+{_SAFETY_NOUN}\b(?!\s+{_RECORD_WORD}\b)",
]
# "alarm override procedure": the verb is part of a noun phrase, not an instruction
SAFETY_NOUN_BEFORE = re.compile(r"\b(?:alarm|safety|interlock|loto|lock.?out|permit|guard|e-?stop|isolation)\s*$")
# a refusal is skipped when the verb is negated just before it ("never bypass", "prevent people from bypassing")
SAFETY_NEGATION = re.compile(r"\b(?:not|never|don'?t|do not|must not|prevent|stop|avoid|without)\b[\w\s,']{0,25}$")

PRIVATE_DATA = [
    r"\b(?:nric|passport|salary|salaries|home address|phone number|fin number|date of birth)\b",
    r"\bpersonal (details|information|data)\b",
]

# creative / general requests that are refused even when a domain word appears
CREATIVE = [
    r"\b(poem|poetry|haiku|limerick|sonnet|lyrics|song|rap|story|essay|joke|riddle|fiction|screenplay|novel)\b",
    r"\bwrite (me )?(a|an) (short )?(story|poem|song|joke|essay|email|letter|speech)\b",
    r"\b(translate|translation)\b",
    r"\bwrite (me )?(some )?(code|python|javascript|a script|sql)\b",
    r"\b(recipe|horoscope|lottery|stock price|bitcoin|football|weather)\b",
]

# a question with none of these words, and no earlier turn, is outside the domain
DOMAIN = re.compile(
    r"\b([a-z]{2,5}-[a-z]?\d{2}|[a-z]{2,5}\d{2,4}|lost.?days?|emp\s?-?\d+|ir-\d{4}-\d+|wo\s?-?\d+|"
    r"machines?|machinery|equipment|assets?|cnc|lathe|mill(ing)?|cranes?|compressors?|pumps?|weld(er|ing)?|blast(ing)?|"
    r"hydraulic|grinder|incidents?|injur\w*|near.?miss(es)?|accidents?|safety|severity|hazards?|"
    r"work ?orders?|maintenance|breakdowns?|repairs?|servic(e|ing)|inspections?|preventive|corrective|"
    r"spares?|stock|inventory|bearings?|seals?|filters?|oil|grease|lubric\w*|coolant|parts?|reorder|supplier|"
    r"sops?|procedures?|loto|lock.?out|tag.?out|confined|permit|hot work|sling|lift(ing)?|rigging|ppe|"
    r"sensors?|vibration|temperature|readings?|nameplates?|capacity|rating|shifts?|night|downtime|cost|costs|"
    r"technicians?|trade|data|records?|policy|policies|ear plugs?|noise|gas|oxygen|isolation|checklist|steps?|"
    r"lifts?|lifted|tandem|slings?|hoist|hook|load|energy|energi[sz]ed?|multimeter|electricians?|electrical|voltage|"
    r"discard|worn|wear|chamber|enter(ing)?|entry|isolat\w*|residual|pressure|valve|hot|torch|fire|attendant|"
    r"rev(ision)?s?|current|latest|document|fault|alarm|drift\w*|running|plant|workshop|factory|jurong|marine|"
    r"risks?|urgent\w*|orders?|order(ing)?|reorder\w*|people|hurt|harm\w*|spend|spent|budget|due|overdue|schedul\w*|"
    r"service|serviced|safe|unsafe|danger\w*|priorit\w*|concern\w*|worr\w*|condition|shape|health\w*|lathes?|"
    r"compressor|audit\w*|breakdown|"
    r"assistant|app|chat|features?|capabilit\w*|benefits?|advantages?|ocr|review|trends?|tables?|history|summar\w*|"
    r"manufacturer|model|serial|weight|power|kw|rpm|lead time|minimum|quantity|part number|sensor|logs?|"
    r"interlocks?|guards?|bypass\w*|vibrating|vibrate\w*|temperatures?|cmms|mysql|sources?|evidence)\b"
)

# --- detectors that set flags but do not refuse --------------------------------
# forward-looking schedule questions: the data holds past and open work orders only
SCHEDULE = [
    r"\bnext (service|maintenance|inspection|pm|overhaul|calibration)\b",
    r"\b(service|maintenance|inspection|calibration|overhaul) (is |are )?(due|scheduled|planned|coming up)\b",
    r"\bwhen (is|are|will|should)\b.{0,40}\b(due|serviced|inspected|maintained|replaced|overhauled)\b",
    r"\b(overdue|upcoming|due date|service interval|maintenance schedule)\b",
    r"\bwhat maintenance is scheduled\b",
]

INFERENCE = [
    r"\b(in )?(good|bad|poor|fine|healthy|decent|okay|ok) (shape|condition|health|state)\b|\bhealth of\b|\bhow (healthy|good|bad) is\b",
    r"\b(biggest|main|top|greatest|worst|key) (risk|risks|concern|concerns|worry|worries|problem|problems|danger)\b|\bworr(y|ies|ied)\b",
    r"\bwhy\b",
    r"\broot ?cause\b|\bwhat\b.{0,25}\bcaus(e|es|ed|ing)\b|\bcause of\b|\bdue to what\b",
    r"\bfailure modes?\b",
    r"\b(about|going|likely|set|due) to (fail|break|seize|stop|trip)\b|\bwill (it|this|that|the \w+) (fail|break|seize)\b",
    r"\bimminent\b|\bimpending\b",
    r"\bremaining (useful )?(life|lifetime)\b|\brul\b",
    r"\b(is it|is the \w+[- ]?\d*|is this) safe to (run|use|operate|keep running)\b|\bsafe to (run|use|operate|keep running)\b",
    r"\b(needs?|requires?|should (we|i) do) (urgent |immediate )?(maintenance|servicing|repair|replacing|replacement)\b",
    r"\bpredict\w*\b|\bforecast\w*\b|\blikelihood\b|\bprobability of\b",
    r"\bshould we (replace|shut|stop|service|repair)\b",
    r"\bfeel(s|ing)? (off|wrong|odd)\b",
]

MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_MONTH_RE = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
MONTH_YEAR = re.compile(rf"\b{_MONTH_RE}\.?,?\s*(?:of\s+)?(20\d{{2}})\b")
YEAR_MONTH_NUM = re.compile(r"\b(20\d{2})[-/](0?[1-9]|1[0-2])\b")
BARE_FUTURE = [
    r"\b(next|coming|upcoming) (month|quarter|year|week)\b",
    r"\b(tomorrow|going forward|in the future|from now)\b",
    r"\b(in|by|during|for) 20(2[7-9]|[3-9]\d)\b",
    r"\bq[34] 2026\b",
]

MISSING_DOCUMENT = [
    r"\b5[- ]?why\b|\bfive[- ]whys?\b",
    r"\broot cause analysis\b|\brca\b",
    r"\binvestigation (report|document|findings)\b",
    r"\bcorrective action (plan|report)\b",
]

# --- fixed refusal messages ------------------------------------------------------
MESSAGES = {
    "NAME_REQUEST": (
        "I cannot give out names or personal details of employees. Staff identities are kept out of what I can see. "
        "I can give counts by year, machine, shift or severity instead."
    ),
    "PERSON_RANKING": (
        "I do not rank or compare individual people. Injury data about a person is sensitive and I only report it in aggregate. "
        "I can show incidents by machine, year, shift or severity instead."
    ),
    "WRITE_INTENT": (
        "I am read-only. I cannot change, add or delete any record. "
        "I can look up what is currently recorded, for example the incident, work order or spares level you have in mind."
    ),
    "INJECTION": (
        "I cannot follow that request. I answer questions about the company's machines, incidents, work orders, spares and safety procedures, "
        "using the recorded data only."
    ),
    "SAFETY_BYPASS": "I cannot help bypass safety controls. Follow the approved SOP and consult the safety officer.",
    "PRIVATE_DATA": "I cannot provide personnel or private information.",
    "OFF_TOPIC": (
        "That is outside what I can help with. I answer questions about Jurong Marine's machines, incidents, work orders, spare parts, "
        "sensor readings and safety procedures. Try asking about one of those."
    ),
    "TOO_LONG": "That question is too long. Please shorten it to a few sentences and ask again.",
    "EMPTY": "Please type a question about the machines, incidents, work orders, spares or safety procedures.",
}

