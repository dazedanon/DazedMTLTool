"""Unit-check the tolerant parser against both observed failure modes."""
import sys

sys.path.insert(0, r"c:\Users\sw\Desktop\Games\CoinPussy\tools\scripts")
from unitytl.batch import parse_json_object  # noqa: E402

Q = chr(34)
BS = chr(92)

cases = []

# Class A: stray dakuten quote inside a value (the あ" transliteration).
cases.append((
    "stray quote in value",
    '{"1":"Everyone... enjoy the show? Aa' + Q + '♥","2":"Next line"}',
    {"1": "Everyone... enjoy the show? Aa" + Q + "♥", "2": "Next line"},
))

# Class B: draft object, self-correction, then the real object.
cases.append((
    "self-corrected double object",
    '{"1":"draft"}' + BS + 'n' + BS + 'nWait, I need all 3.' + BS + 'n' +
    '{"1":"real one","2":"two","3":"three"}',
    {"1": "real one", "2": "two", "3": "three"},
))

# Both at once.
cases.append((
    "both failure modes together",
    '{"1":"partial Aa' + Q + 'h"}  Wait, redo.  ' +
    '{"1":"full Aa' + Q + 'h♥","2":"second"}',
    {"1": "full Aa" + Q + "h♥", "2": "second"},
))

# Must not regress clean input, escaped quotes, or fenced JSON.
cases.append((
    "clean input untouched",
    '{"1":"nothing odd here","2":"line' + BS + 'nbreak"}',
    {"1": "nothing odd here", "2": "line\nbreak"},
))
cases.append((
    "properly escaped quote preserved",
    '{"1":"she said ' + BS + Q + 'hello' + BS + Q + ' softly"}',
    {"1": 'she said ' + Q + 'hello' + Q + ' softly'},
))
cases.append((
    "fenced json",
    '```json' + chr(10) + '{"1":"fenced"}' + chr(10) + '```',
    {"1": "fenced"},
))
cases.append((
    "colon and brace inside text",
    '{"1":"ratio 3:1, see {this}","2":"ok"}',
    {"1": "ratio 3:1, see {this}", "2": "ok"},
))

failed = 0
for name, raw, want in cases:
    try:
        got = parse_json_object(raw)
    except Exception as e:
        print(f"FAIL {name}: raised {e!r}")
        failed += 1
        continue
    if got == want:
        print(f"ok   {name}")
    else:
        print(f"FAIL {name}:{chr(10)}  got  {got!r}{chr(10)}  want {want!r}")
        failed += 1

print(f"{chr(10)}{len(cases) - failed}/{len(cases)} passed")
sys.exit(1 if failed else 0)
