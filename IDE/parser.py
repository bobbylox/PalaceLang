import re
import json
import copy
import os
from typing import Any, Dict, List, Optional, Tuple, NamedTuple

# Load built-in type definitions once at module level.
_BUILTIN_PATH = os.path.join(os.path.dirname(__file__), "..", "builtin.json")
with open(_BUILTIN_PATH) as _f:
    BUILTIN = json.load(_f)

# Scalar types valid as box value-type constraints.
VALUE_TYPES: List[str] = BUILTIN["_value_types"]

# AST-level default structures for each type.
_DEFAULTS: Dict[str, Any] = BUILTIN["_defaults"]


def _default(type_name: str) -> Dict:
    """Return a fresh (deep-copied) AST default for the given type."""
    return copy.deepcopy(_DEFAULTS[type_name])


# Canonical property names for possessive-set commands.
_PROP_MAP: Dict[str, str] = {
    "value type": "value_type",
    "value":      "value",
    "comment":    "comment",
    "name":       "name",
}

# Structural (non-user-settable) keys for each type, derived from BUILTIN.
# A key is structural if its value in the type definition is itself a typed
# sub-object (a dict with a "type" key) — these represent the fixed architecture
# of the type and must not be mutated or renamed by the user.
_STRUCTURAL_KEYS: Dict[str, frozenset] = {
    type_name: frozenset(
        k for k, v in type_def.items()
        if isinstance(v, dict) and "type" in v
    )
    for type_name, type_def in BUILTIN.items()
    if not type_name.startswith("_") and isinstance(type_def, dict)
}

# Reserved keys in a flat type_def dict (everything else is a member).
_TYPE_DEF_RESERVED = frozenset({"type", "parent"})

# Builtin type names — used to distinguish user-type instances from builtins.
_BUILTIN_TYPES = frozenset({
    "palace", "wing", "room", "device", "chain", "box", "bag", "type_def", "link"
})

# Plural / alias → canonical kind name used internally.
_KIND_NORMALIZE: Dict[str, str] = {
    "palaces": "palace",
    "wings":   "wing",
    "rooms":   "room",
    "type":    "type_def",
    "types":   "type_def",
    "devices": "device",
    "chains":  "chain",
    "boxes":   "box",
    "bags":    "bag",
}

# Builtin types that live in room.contents and are generically enterable.
# Derived from _DEFAULTS, excluding structural navigation types and link.
_ROOM_CONTENT_TYPES: frozenset = frozenset(
    k for k in _DEFAULTS
    if k not in {"palace", "wing", "room", "type_def", "link"}
)

# Maps action op prefixes to the kind of object whose name should be recorded
# in _last_by_type.  Checked in order; first prefix match wins.
_OP_TO_KIND: List[Tuple[str, str]] = [
    ("palace",         "palace"),
    ("enter.palace",   "palace"),
    ("wing",           "wing"),
    ("enter.wing",     "wing"),
    ("room",           "room"),
    ("enter.room",     "room"),
    ("device",         "device"),
    ("enter.device",   "device"),
    ("chain",          "chain"),
    ("enter.chain",    "chain"),
    ("bag",            "bag"),
    ("enter.bag",      "bag"),
    ("box",            "box"),
    ("enter.box",      "box"),
    ("type",           "type"),
    ("enter.type",     "type"),
    ("instance",       "instance"),
    ("enter.instance", "instance"),
]

# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------

class Token(NamedTuple):
    kind: str   # WORD, NUM, APOS, QM, END
    val: Any    # lowercased word for WORD, numeric for NUM, None otherwise
    orig: str   # original text (for value reconstruction)


def _tokenize(text: str) -> List[Token]:
    """Tokenize text into a list of Tokens (with END sentinel).

    Token kinds:
      WORD  — any word token, val is lowercased
      NUM   — numeric literal, val is int or float
      APOS  — literal 's (possessive / "link")
      QM    — literal ?
      END   — sentinel
    """
    tokens: List[Token] = []
    # Split on whitespace; handle 's and ? specially
    i = 0
    raw_words = text.split()
    for raw in raw_words:
        # Check for trailing ? or 's
        while raw.endswith("?"):
            core = raw[:-1]
            if core:
                _add_word_or_num(tokens, core)
            tokens.append(Token("QM", None, "?"))
            raw = ""
            break
        if not raw:
            continue
        # Handle 's suffix
        if raw.endswith("'s") or raw.endswith("'"):
            core = raw[:-2] if raw.endswith("'s") else raw[:-1]
            if core:
                _add_word_or_num(tokens, core)
            tokens.append(Token("APOS", None, "'s"))
            continue
        _add_word_or_num(tokens, raw)
    tokens.append(Token("END", None, ""))
    return tokens


def _add_word_or_num(tokens: List[Token], raw: str):
    """Add a WORD or NUM token for the given raw string."""
    # Try int
    try:
        v = int(raw)
        tokens.append(Token("NUM", v, raw))
        return
    except ValueError:
        pass
    # Try float
    try:
        v = float(raw)
        tokens.append(Token("NUM", v, raw))
        return
    except ValueError:
        pass
    tokens.append(Token("WORD", raw.lower(), raw))


# ---------------------------------------------------------------------------
# Earley Parser
# ---------------------------------------------------------------------------
# Items: (rule_idx, dot, origin) stored as tuples for hashability.
# Grammar: _RULES list of (lhs, rhs_tuple); _NT_IDX maps lhs -> [rule_idx].
# Terminals: lowercase str = match WORD with that value; "WORD"/"NUM"/"APOS"/"QM"
#            = match any token of that kind.
# Non-terminals: strings whose first character is uppercase.
# Epsilon rules: rhs = () (empty tuple).

_RULES: List[Tuple[str, Tuple]] = []
_NT_IDX: Dict[str, List[int]] = {}


def _R(lhs: str, *rhs: str) -> int:
    """Add a grammar rule; return its index."""
    idx = len(_RULES)
    _RULES.append((lhs, rhs))
    _NT_IDX.setdefault(lhs, []).append(idx)
    return idx


_TOKEN_TYPES = {"WORD", "NUM", "APOS", "QM", "END"}

def _is_nt(sym: str) -> bool:
    return bool(sym) and sym[0].isupper() and sym not in _TOKEN_TYPES


def _terminal_matches(sym: str, tok: Token) -> bool:
    if sym == "WORD":  return tok.kind == "WORD"
    if sym == "NUM":   return tok.kind == "NUM"
    if sym == "APOS":  return tok.kind == "APOS"
    if sym == "QM":    return tok.kind == "QM"
    return tok.kind == "WORD" and tok.val == sym


# ── Optional helpers (epsilon + filled) ──────────────────────────────────────
_R("OptThe");         _R("OptThe",    "the")
_R("OptQM");          _R("OptQM",     "QM")
_R("OptApos");        _R("OptApos",   "APOS")
_R("OptNew");         _R("OptNew",    "new")
_R("OptCalled");      _R("OptCalled", "called");  _R("OptCalled", "named")
_R("OptWhatIs");      _R("OptWhatIs", "what", "is", "OptThe")
_R("OptValueOf");     _R("OptValueOf","value", "of")

# ── Name non-terminals ────────────────────────────────────────────────────────
_R("Sname", "WORD")                              # exactly one word
_R("Mname", "WORD")                              # one word, no stop
_R("Mname", "WORD", "stop")                      # one word + stop
_R("Mname", "WORD", "MnameTail")                 # multi-word
_R("MnameTail", "WORD")
_R("MnameTail", "WORD", "stop")
_R("MnameTail", "WORD", "MnameTail")

# ── Value: any token sequence (at least one) until END ────────────────────────
_R("Value", "WORD");  _R("Value", "NUM");  _R("Value", "APOS")
_R("Value", "WORD", "Value")
_R("Value", "NUM",  "Value")
_R("Value", "APOS", "Value")

# ── Command rules (lower index = higher priority) ─────────────────────────────
_LOOK_AROUND  = _R("Command", "look", "around")
_WHEREAMI     = _R("Command", "where", "am", "i", "OptQM")
_STEP_LENGTH  = _R("Command", "what", "is", "OptThe", "step", "length", "OptQM")
_QUERY_LINK   = _R("Command", "OptWhatIs", "OptValueOf", "Sname", "OptApos",
                               "link", "NUM", "OptQM")
_LENGTH       = _R("Command", "OptWhatIs", "length", "of", "Sname", "OptQM")

_PALACE       = _R("Command", "OptNew", "palace", "OptCalled", "Mname")
_ENTER_TYPED  = _R("Command", "enter", "OptNew", "Sname", "OptCalled", "Mname")
_ENTER        = _R("Command", "enter", "Sname")
_GO_TO        = _R("Command", "go", "to", "Sname")
_GO_OUTSIDE   = _R("Command", "go", "outside")
_EXIT         = _R("Command", "exit")

_WING         = _R("Command", "OptNew", "wing", "OptCalled", "Sname")
_ROOM         = _R("Command", "OptNew", "room", "OptCalled", "Sname")
_CHAIN_TYPED  = _R("Command", "OptNew", "chain", "of", "Sname", "OptCalled", "Mname")
_CHAIN        = _R("Command", "OptNew", "chain", "OptCalled", "Mname")
_BAG_TYPED    = _R("Command", "OptNew", "bag",   "of", "Sname", "OptCalled", "Mname")
_BAG          = _R("Command", "OptNew", "bag",   "OptCalled", "Mname")
_BOX_N_TYPED  = _R("Command", "OptNew", "box",   "OptCalled", "Sname", "of", "Sname")   # box NAME of TYPE
_BOX_OF_NAMED = _R("Command", "OptNew", "box",   "of", "Sname", "OptCalled", "Mname")   # box of TYPE NAME
_BOX_OF_ANON  = _R("Command", "OptNew", "box",   "of", "Sname")                         # box of TYPE
_BOX          = _R("Command", "OptNew", "box",   "OptCalled", "Mname")
_DEVICE       = _R("Command", "OptNew", "device",  "OptCalled", "Sname")
_TYPE_FROM    = _R("Command", "OptNew", "type",    "OptCalled", "Mname", "from", "Sname")
_TYPE         = _R("Command", "OptNew", "type",    "OptCalled", "Mname")

_APPEND_LINK  = _R("Command", "append", "link", "to", "Mname")
_APPEND_VAL   = _R("Command", "append", "Value", "to", "Mname")

_SET_LVAL      = _R("Command", "set", "link", "value", "to", "Value")
_SET_LVAL2     = _R("Command", "set", "link", "value", "Value")
_SET_INPUT_N   = _R("Command", "set", "input", "name", "to", "Value")
_SET_INPUT_T   = _R("Command", "set", "input", "type", "to", "Value")
_SET_COMMENT   = _R("Command", "set", "comment", "to", "Value")
_SET_STEP      = _R("Command", "set", "step",    "NUM", "to", "Value")
_SET_PATTERN   = _R("Command", "set", "pattern", "to", "Value")
_SET           = _R("Command", "set", "Value",   "to", "Value")

_RENAME_TO     = _R("Command", "rename", "Value", "to",   "Value")
_RENAME_S      = _R("Command", "rename", "Value", "stop", "Value")
_RENAME        = _R("Command", "rename", "Value", "Value")

_THEN          = _R("Command", "then", "Value")
_STEP_SH       = _R("Command", "step", "NUM", "Value")

_RUN_FULL      = _R("Command", "run", "Sname", "APOS", "Sname", "APOS", "Sname")
_RUN_FULL_ON   = _R("Command", "run", "Sname", "APOS", "Sname", "APOS", "Sname",
                                "on", "Value")
_RUN_FULL_NA   = _R("Command", "run", "Sname", "Sname", "Sname")
_RUN_FULL_ON_NA= _R("Command", "run", "Sname", "Sname", "Sname", "on", "Value")
_RUN_ROOM      = _R("Command", "run", "Sname", "APOS", "Sname")
_RUN_ROOM_ON   = _R("Command", "run", "Sname", "APOS", "Sname", "on", "Value")
_RUN_ROOM_NA   = _R("Command", "run", "Sname", "Sname")
_RUN_ROOM_ON_NA= _R("Command", "run", "Sname", "Sname", "on", "Value")
_RUN           = _R("Command", "run", "Sname")
_RUN_ON        = _R("Command", "run", "Sname", "on", "Value")

_DELETE        = _R("Command", "delete", "Value")

_INSTANTIATE   = _R("Command", "OptNew", "Sname", "OptCalled", "Sname")


# ── Earley algorithm ──────────────────────────────────────────────────────────

def _earley(tokens: List[Token]) -> List[set]:
    """
    Run the Earley parsing algorithm.  Items are (rule_idx, dot, origin).
    Returns chart[0..n] where chart[i] is the set of completed/active items
    at position i.  Epsilon rules are completed immediately during prediction.
    """
    n = len(tokens)
    chart: List[set] = [set() for _ in range(n + 1)]

    # Seed with all Command rules at position 0
    for ri in _NT_IDX.get("Command", []):
        chart[0].add((ri, 0, 0))

    for i in range(n + 1):
        queue = list(chart[i])
        qi = 0
        while qi < len(queue):
            item = queue[qi]; qi += 1
            ri, dot, origin = item
            lhs, rhs = _RULES[ri]

            if dot == len(rhs):
                # COMPLETE: advance items in chart[origin] waiting for lhs
                for prev in list(chart[origin]):
                    pri, pdot, porigin = prev
                    plhs, prhs = _RULES[pri]
                    if pdot < len(prhs) and prhs[pdot] == lhs:
                        new = (pri, pdot + 1, porigin)
                        if new not in chart[i]:
                            chart[i].add(new)
                            queue.append(new)
            else:
                sym = rhs[dot]
                if _is_nt(sym):
                    # PREDICT: add rules for sym; handle epsilon immediately
                    for new_ri in _NT_IDX.get(sym, []):
                        nlhs, nrhs = _RULES[new_ri]
                        if not nrhs:
                            # Epsilon: add the completed item, then advance parent
                            eps = (new_ri, 0, i)
                            if eps not in chart[i]:
                                chart[i].add(eps)
                            adv = (ri, dot + 1, origin)
                            if adv not in chart[i]:
                                chart[i].add(adv)
                                queue.append(adv)
                        else:
                            new = (new_ri, 0, i)
                            if new not in chart[i]:
                                chart[i].add(new)
                                queue.append(new)
                # terminals are scanned below

        # SCAN: advance items at chart[i] whose next terminal matches tokens[i]
        if i < n and tokens[i].kind != "END":
            tok = tokens[i]
            for item in chart[i]:
                ri, dot, origin = item
                lhs, rhs = _RULES[ri]
                if dot < len(rhs) and not _is_nt(rhs[dot]):
                    if _terminal_matches(rhs[dot], tok):
                        new = (ri, dot + 1, origin)
                        if new not in chart[i + 1]:
                            chart[i + 1].add(new)

    return chart


# ── Parse tree extraction ─────────────────────────────────────────────────────

def _nt_complete(chart: List[set], nt: str, start: int, end: int) -> bool:
    """True if NT has a completed derivation spanning tokens[start:end]."""
    for ri, dot, origin in chart[end]:
        if origin == start and dot == len(_RULES[ri][1]) and _RULES[ri][0] == nt:
            return True
    return False


def _find_spans(chart, rhs, rhs_idx, pos, end, tokens):
    """
    Reconstruct spans for rhs[rhs_idx:] covering tokens[pos:end].
    Returns list of (sym, start, end, sub) or None.
    sub=None for terminals; sub=list for NTs (sub-spans of their derivation).
    Opt* NTs use longest-first (greedy) matching; all others use shortest-first.
    """
    if rhs_idx == len(rhs):
        return [] if pos == end else None

    sym = rhs[rhs_idx]
    if _is_nt(sym):
        # Opt* nonterminals: try longest span first (greedy), so APOS/tokens
        # are consumed by the optional NT rather than by the following Value NT.
        if sym.startswith("Opt"):
            candidates = range(end, pos - 1, -1)
        else:
            candidates = range(pos, end + 1)
        for nt_end in candidates:
            if not _nt_complete(chart, sym, pos, nt_end):
                continue
            rest = _find_spans(chart, rhs, rhs_idx + 1, nt_end, end, tokens)
            if rest is not None:
                sub = _find_nt_spans(chart, sym, pos, nt_end, tokens)
                return [(sym, pos, nt_end, sub)] + rest
        return None
    else:
        if pos >= end:
            return None
        tok = tokens[pos]
        if _terminal_matches(sym, tok):
            rest = _find_spans(chart, rhs, rhs_idx + 1, pos + 1, end, tokens)
            if rest is not None:
                return [(sym, pos, pos + 1, None)] + rest
        return None


def _find_nt_spans(chart, nt, start, end, tokens):
    """Return sub-spans for one completed derivation of NT from start to end."""
    for ri, dot, origin in chart[end]:
        lhs, rhs = _RULES[ri]
        if lhs == nt and origin == start and dot == len(rhs):
            spans = _find_spans(chart, rhs, 0, start, end, tokens)
            if spans is not None:
                return spans
    return []


def _parse_expr(s: str) -> Dict:
    """Recursively parse an expression string into a typed command/value object.

    Every returned object has a "type" field:
      {"type": "integer",   "value": 2}
      {"type": "number",    "value": 3.14}
      {"type": "boolean",   "value": true}
      {"type": "reference", "name":  "radius"}
      {"type": "command",   "operator": "...", "arguments": [...]}

    Operator precedence matches the original string-scanning interpreter:
      chain link / length of  (highest — checked before arithmetic)
      squared / cubed
      times / divided by
      plus / minus
      comparisons             (lowest)
    """
    s = s.strip()
    if not s:
        return None

    # literal integer
    try:
        return {"type": "integer", "value": int(s)}
    except ValueError:
        pass

    # literal float
    try:
        return {"type": "number", "value": float(s)}
    except ValueError:
        pass

    # literal boolean
    if s.lower() == "true":
        return {"type": "boolean", "value": True}
    if s.lower() == "false":
        return {"type": "boolean", "value": False}

    # length of CHAIN  (high priority — checked before arithmetic)
    m = re.match(r"^length of (\w+)$", s)
    if m:
        return {"type": "command", "operator": "length of",
                "arguments": [{"type": "reference", "name": m.group(1)}]}

    # CHAIN link EXPR  (high priority — the index expression takes the rest of
    # the string, allowing arithmetic inside the index, e.g. "seq link n minus 1")
    m = re.match(r"^(\w+) link (.+)$", s)
    if m:
        return {"type": "command", "operator": "chain link",
                "arguments": [{"type": "reference", "name": m.group(1)},
                               _parse_expr(m.group(2))]}

    # comparison operators (lowest arithmetic precedence) — split on first match
    for op_str, op_name in [
        ("is less than",    "less than"),
        ("is greater than", "greater than"),
        ("is equal to",     "equal to"),
    ]:
        pat = f" {op_str} "
        if pat in s:
            left, right = s.split(pat, 1)
            return {"type": "command", "operator": op_name,
                    "arguments": [_parse_expr(left), _parse_expr(right)]}

    # addition — split on all occurrences, left-fold
    if " plus " in s:
        parts = s.split(" plus ")
        result = _parse_expr(parts[0])
        for p in parts[1:]:
            result = {"type": "command", "operator": "plus",
                      "arguments": [result, _parse_expr(p)]}
        return result

    # subtraction — rsplit for left-associativity
    if " minus " in s:
        a, b = s.rsplit(" minus ", 1)
        return {"type": "command", "operator": "minus",
                "arguments": [_parse_expr(a), _parse_expr(b)]}

    # multiplication — split on all occurrences, left-fold
    if " times " in s:
        parts = s.split(" times ")
        result = _parse_expr(parts[0])
        for p in parts[1:]:
            result = {"type": "command", "operator": "multiply",
                      "arguments": [result, _parse_expr(p)]}
        return result

    # division
    if " divided by " in s:
        a, b = s.split(" divided by ", 1)
        return {"type": "command", "operator": "divide",
                "arguments": [_parse_expr(a), _parse_expr(b)]}

    # postfix powers
    if s.endswith(" squared"):
        return {"type": "command", "operator": "squared",
                "arguments": [_parse_expr(s[:-8])]}
    if s.endswith(" cubed"):
        return {"type": "command", "operator": "cubed",
                "arguments": [_parse_expr(s[:-6])]}

    # CHAIN EXPR shorthand (e.g. "sequence input") — catch-all two-word form
    m = re.match(r"^(\w+) (\w.*)$", s)
    if m:
        return {"type": "command", "operator": "chain get",
                "arguments": [{"type": "reference", "name": m.group(1)},
                               _parse_expr(m.group(2))]}

    # bare variable / input name
    return {"type": "reference", "name": s}


class IDE:
    """Voice-command -> AST translator for Palace Language.

    Keeps a workspace in-memory and can dump it as JSON.
    Covers all commands in the canonical example session.
    """

    def __init__(self):
        self.ast: Dict[str, Any] = {"palaces": {}}
        self.current = {
            "palace": None, "wing": None, "room": None,
            "type_def": None, "instance": None, "bag": None, "device": None, "process_chain": None
        }
        # Clipboard: tracks the last name seen overall ("it") and per type ("the room" etc.)
        self._last_by_type: Dict[str, str] = {}
        self._last_link_chain: Optional[str] = None  # for "set link value"
        self._last_box: Optional[str] = None          # for "box of TYPE" references
        self._box_counter: int = 0                    # auto-names anonymous boxes

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, path: str):
        with open(path, "w") as f:
            json.dump(self.ast, f, indent=2)

    def load(self, path: str):
        with open(path) as f:
            self.ast = json.load(f)

    # ------------------------------------------------------------------
    # AST helpers
    # ------------------------------------------------------------------

    def _ensure_palace(self, name: str) -> Dict:
        return self.ast["palaces"].setdefault(name, _default("palace"))

    def _ensure_wing(self, palace: str, wing: str) -> Dict:
        p = self._ensure_palace(palace)
        return p.setdefault("wings", {}).setdefault(wing, _default("wing"))

    def _ensure_room(self, palace: str, room: str,
                     wing: Optional[str] = None) -> Dict:
        if wing:
            w = self._ensure_wing(palace, wing)
            return w["rooms"].setdefault(room, _default("room"))
        p = self._ensure_palace(palace)
        return p["rooms"].setdefault(room, _default("room"))

    def _current_room_obj(self) -> Optional[Dict]:
        p = self.current["palace"]
        if p is None:
            return None
        room = self.current["room"]
        if room is None:
            # default to palace-level lobby (never inside a wing implicitly)
            return self._ensure_room(p, "lobby", None)
        return self._ensure_room(p, room, self.current["wing"])

    def _current_type_def_obj(self) -> Optional[Dict]:
        palace = self.current["palace"]
        td = self.current["type_def"]
        if palace is None or td is None:
            return None
        return self.ast["palaces"].get(palace, {}).get("types", {}).get(td)

    def _current_device_obj(self) -> Optional[Dict]:
        dev = self.current["device"]
        if dev is None:
            return None
        td = self._current_type_def_obj()
        if td is not None:
            return td.get(dev)
        room = self._current_room_obj()
        if room is None:
            return None
        return room.get("contents", {}).get(dev)

    # ------------------------------------------------------------------
    # Pre-processing
    # ------------------------------------------------------------------

    def _preprocess(self, utterance: str) -> str:
        t = utterance.strip()
        # "over" is a command-end marker — strip it at utterance level
        if t.endswith(" over"):
            t = t[:-5].strip()
        # "stop" is a string-end marker — handled at the value level, NOT here
        # resolve "it" pronoun and "the TYPE" references
        if self._last_by_type.get("it"):
            t = re.sub(r'\bit\b', self._last_by_type["it"], t, flags=re.IGNORECASE)
        def _replace_the(m: re.Match) -> str:
            kind = m.group(1).lower()
            return self._last_by_type.get(kind, m.group(0))
        t = re.sub(r'\bthe (\w+)\b', _replace_the, t, flags=re.IGNORECASE)
        return t


    # ------------------------------------------------------------------
    # Main dispatcher (Earley parser)
    # ------------------------------------------------------------------

    def process(self, utterance: str) -> Dict[str, Any]:
        t = self._preprocess(utterance)
        tokens = _tokenize(t)
        # END token is last; it's at index len(tokens)-1
        k = len(tokens) - 1
        chart = _earley(tokens)

        # Find lowest-index completed Command rule spanning tokens[0:k]
        for ri in _NT_IDX.get("Command", []):
            lhs, rhs = _RULES[ri]
            if (ri, len(rhs), 0) in chart[k]:
                spans = _find_spans(chart, rhs, 0, 0, k, tokens)
                if spans is not None:
                    res = self._dispatch_earley(ri, spans, tokens)
                    if isinstance(res, dict):
                        if "name" in res:
                            name = res["name"]
                            self._last_by_type["it"] = name
                            op = res.get("op", "")
                            for prefix, kind in _OP_TO_KIND:
                                if op.startswith(prefix):
                                    self._last_by_type[kind] = name
                                    if kind == "instance" and "type" in res:
                                        self._last_by_type[res["type"]] = name
                                    break
                        if "error" in res:
                            return {"ok": False, "error": res["error"]}
                    return {"ok": True, "action": self._action_to_command(res)}

        action = self._try_type_patterns(t)
        if action is not None:
            return {"ok": True, "action": self._action_to_command(action)}

        try:
            v = self._eval_arith(t)
            if isinstance(v, float) and v.is_integer():
                v = int(v)
            return {"ok": True, "action": self._action_to_command({"op": "expr.result", "value": v})}
        except (ValueError, TypeError, ZeroDivisionError):
            pass
        return {"ok": False, "error": f"unrecognized: {t}"}

    def _action_to_command(self, action: dict) -> dict:
        """Convert an op-dict from _dispatch_earley into a standard command object."""
        result = dict(action)
        if "op" in result:
            result["operator"] = result.pop("op")
        result.setdefault("type", "command")
        result.setdefault("arguments", [])
        return result

    def _dispatch_earley(self, ri: int, spans, tokens: List[Token]) -> Dict:
        """Dispatch to the appropriate _cmd_* handler based on the matched rule index."""

        def _sname(n: int = 0) -> Optional[str]:
            """Return the nth Sname value (original case, single word)."""
            cnt = 0
            for sym, s, e, _ in spans:
                if sym == "Sname":
                    if cnt == n:
                        return " ".join(tokens[i].orig for i in range(s, e))
                    cnt += 1
            return None

        def _mname(n: int = 0) -> Optional[str]:
            """Return the nth Mname value (stop stripped)."""
            cnt = 0
            for sym, s, e, _ in spans:
                if sym == "Mname":
                    if cnt == n:
                        words = [tokens[i].orig for i in range(s, e)
                                 if not (tokens[i].kind == "WORD" and tokens[i].val == "stop")]
                        return " ".join(words)
                    cnt += 1
            return None

        def _value(n: int = 0) -> Optional[str]:
            """Return the nth Value as a reconstructed string."""
            cnt = 0
            for sym, s, e, _ in spans:
                if sym == "Value":
                    if cnt == n:
                        return " ".join(tokens[i].orig for i in range(s, e))
                    cnt += 1
            return None

        def _num(n: int = 0) -> Optional[Any]:
            """Return the nth NUM token value."""
            cnt = 0
            for sym, s, e, sub in spans:
                if sym == "NUM":
                    if cnt == n:
                        return tokens[s].val
                    cnt += 1
            # Also search in all spans including sub-spans
            cnt = 0
            for tok in tokens:
                if tok.kind == "NUM":
                    if cnt == n:
                        return tok.val
                    cnt += 1
            return None

        def _opt_present(opt_sym: str) -> bool:
            """True if an optional NT consumed at least one token (non-epsilon)."""
            for sym, s, e, _ in spans:
                if sym == opt_sym:
                    return e > s
            return False

        # Helper: find NUMs in token list between positions
        def _find_num_in_tokens(start: int, end: int) -> Optional[Any]:
            for i in range(start, end):
                if tokens[i].kind == "NUM":
                    return tokens[i].val
            return None

        # For rules with NUM directly in the rhs (not wrapped in a NT), 
        # we need to find them in spans as terminal entries
        def _terminal_num(n: int = 0) -> Optional[Any]:
            cnt = 0
            for sym, s, e, sub in spans:
                if sym == "NUM":
                    if cnt == n:
                        return tokens[s].val
                    cnt += 1
            return None

        # ── Dispatch by rule index ─────────────────────────────────────────────────────

        if ri == _LOOK_AROUND:
            return self._cmd_look_around()

        if ri == _WHEREAMI:
            return self._cmd_whereami()

        if ri == _STEP_LENGTH:
            return self._cmd_step_length()

        if ri == _QUERY_LINK:
            # set "chain" OptWhatIs OptValueOf Sname OptApos link NUM OptQM
            chain = _sname(0)
            value_of = _opt_present("OptValueOf")
            # Find the NUM token in the span
            num_val = None
            for sym, s, e, sub in spans:
                if sym == "NUM":
                    num_val = tokens[s].val
                    break
            return self._cmd_query_link(
                chain=chain,
                idx=str(int(num_val)) if num_val is not None else "1",
                value_of="value of " if value_of else None
            )

        if ri == _LENGTH:
            return self._cmd_length(chain=_sname(0))

        if ri == _PALACE:
            return self._cmd_palace(name=_mname(0))

        if ri == _ENTER_TYPED:
            return self._cmd_enter_typed(kind=_sname(0), name=_mname(0))

        if ri == _ENTER:
            return self._cmd_enter(name=_sname(0))

        if ri == _GO_TO:
            return self._cmd_go_to(name=_sname(0))

        if ri == _GO_OUTSIDE:
            return self._cmd_go_outside()

        if ri == _EXIT:
            return self._cmd_exit()

        if ri == _WING:
            return self._cmd_wing(name=_sname(0))

        if ri == _ROOM:
            return self._cmd_room(name=_sname(0))

        if ri == _CHAIN_TYPED:
            # OptNew "chain" "of" Sname OptCalled Mname -> btype=Sname, name=Mname
            return self._cmd_chain(name=_mname(0), btype=_sname(0))

        if ri == _CHAIN:
            return self._cmd_chain(name=_mname(0), btype=None)

        if ri == _BAG_TYPED:
            return self._cmd_bag(name=_mname(0), btype=_sname(0))

        if ri == _BAG:
            return self._cmd_bag(name=_mname(0), btype=None)

        if ri == _BOX_N_TYPED:
            # OptNew "box" OptCalled Sname "of" Sname -> name=sname(0), btype=sname(1)
            return self._cmd_box_typed(btype=_sname(1), name=_sname(0))

        if ri == _BOX_OF_NAMED:
            # OptNew "box" "of" Sname OptCalled Mname -> btype=sname(0), name=mname(0)
            return self._cmd_box_typed(btype=_sname(0), name=_mname(0))

        if ri == _BOX_OF_ANON:
            # OptNew "box" "of" Sname -> btype=sname(0), no name
            return self._cmd_box_typed(btype=_sname(0), name=None)

        if ri == _BOX:
            return self._cmd_box(name=_mname(0))

        if ri == _DEVICE:
            return self._cmd_create_device(name=_sname(0))

        if ri == _TYPE_FROM:
            # OptNew "type" OptCalled Mname "from" Sname
            return self._cmd_type_from(name=_mname(0), parent=_sname(0))

        if ri == _TYPE:
            return self._cmd_type(name=_mname(0))

        if ri == _APPEND_LINK:
            # "append" "link" "to" Mname
            return self._cmd_append_link(chain=_mname(0))

        if ri == _APPEND_VAL:
            # "append" Value "to" Mname
            return self._cmd_append_to_chain(value=_value(0), chain=_mname(0))

        if ri == _SET_LVAL:
            # "set" "link" "value" "to" Value
            return self._cmd_set_link_value(value=_value(0))

        if ri == _SET_LVAL2:
            # "set" "link" "value" Value
            return self._cmd_set_link_value(value=_value(0))

        if ri == _SET_INPUT_N:
            return self._cmd_set_input(prop="name", value=_value(0))

        if ri == _SET_INPUT_T:
            return self._cmd_set_input(prop="type", value=_value(0))

        if ri == _SET_COMMENT:
            return self._cmd_set_comment(value=_value(0))

        if ri == _SET_STEP:
            # "set" "step" NUM "to" Value
            num_val = None
            for sym, s, e, sub in spans:
                if sym == "NUM":
                    num_val = tokens[s].val
                    break
            return self._cmd_set_step(
                idx=str(int(num_val)) if num_val is not None else "1",
                body=_value(0)
            )

        if ri == _SET_PATTERN:
            return self._cmd_set_pattern(value=_value(0))

        if ri == _SET:
            # "set" Value "to" Value  — generalized set
            return self._cmd_set(lhs=_value(0), rhs=_value(1))

        if ri in (_RENAME_TO, _RENAME_S, _RENAME):
            return self._cmd_rename(old=_value(0), new=_value(1))

        if ri == _THEN:
            return self._cmd_then(body=_value(0))

        if ri == _STEP_SH:
            # "step" NUM Value
            num_val = None
            for sym, s, e, sub in spans:
                if sym == "NUM":
                    num_val = tokens[s].val
                    break
            return self._cmd_step_shorthand(
                idx=str(int(num_val)) if num_val is not None else "1",
                body=_value(0)
            )

        if ri == _RUN_FULL:
            # "run" Sname APOS Sname APOS Sname
            return self._cmd_run_full(
                palace=_sname(0), room=_sname(1), device=_sname(2), value=None
            )

        if ri == _RUN_FULL_ON:
            # "run" Sname APOS Sname APOS Sname "on" Value
            return self._cmd_run_full(
                palace=_sname(0), room=_sname(1), device=_sname(2), value=_value(0)
            )

        if ri in (_RUN_FULL_NA, _RUN_FULL_ON_NA):
            # "run" Sname Sname Sname ["on" Value]
            return self._cmd_run_full(
                palace=_sname(0), room=_sname(1), device=_sname(2),
                value=_value(0) if ri == _RUN_FULL_ON_NA else None
            )

        if ri == _RUN_ROOM:
            # "run" Sname APOS Sname
            return self._cmd_run_room(room=_sname(0), device=_sname(1), value=None)

        if ri == _RUN_ROOM_ON:
            # "run" Sname APOS Sname "on" Value
            return self._cmd_run_room(room=_sname(0), device=_sname(1), value=_value(0))

        if ri in (_RUN_ROOM_NA, _RUN_ROOM_ON_NA):
            # "run" Sname Sname ["on" Value]
            return self._cmd_run_room(
                room=_sname(0), device=_sname(1),
                value=_value(0) if ri == _RUN_ROOM_ON_NA else None
            )

        if ri == _RUN:
            return self._cmd_run(device=_sname(0), value=None)

        if ri == _RUN_ON:
            return self._cmd_run(device=_sname(0), value=_value(0))

        if ri == _DELETE:
            return self._cmd_delete(spec=_value(0))

        if ri == _INSTANTIATE:
            # OptNew Sname OptCalled Sname -> type_name=sname(0), instance_name=sname(1)
            return self._cmd_instantiate(type_name=_sname(0), instance_name=_sname(1))

        raise ValueError(f"Unknown Earley rule index: {ri}")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _strip_stop(s: str) -> str:
        """Strip trailing ' stop' string-end marker from a value."""
        if s.endswith(" stop"):
            return s[:-5].strip()
        return s

    def _parse_value(self, s: str) -> Any:
        s = self._strip_stop(s.strip())
        try:
            return int(s)
        except ValueError:
            pass
        try:
            return float(s)
        except ValueError:
            pass
        if s.lower() == "true":
            return True
        if s.lower() == "false":
            return False
        if s.lower() == "null":
            return None
        return s

    def _chain_type(self, chain: Dict) -> Optional[str]:
        for link in chain.get("links", []):
            v = link.get("value")
            if v is None:
                continue
            if isinstance(v, bool):
                return "boolean"
            if isinstance(v, (int, float)):
                return "number"
            if isinstance(v, str):
                return "string"
        return None

    # ------------------------------------------------------------------
    # Command handlers
    # ------------------------------------------------------------------

    def _cmd_palace(self, name: str) -> Dict:
        if name in _BUILTIN_TYPES or name in VALUE_TYPES:
            return {"error": f"{name!r} is a built-in type name"}
        self._ensure_palace(name)
        self._ensure_room(name, "lobby")   # every palace starts with lobby
        self.current = {
            "palace": name, "wing": None, "room": None,
            "type_def": None, "instance": None, "bag": None, "device": None, "process_chain": None
        }
        return {"op": "palace.create", "name": name}

    def _cmd_enter(self, name: str) -> Dict:
        # enter a command chain? (must be in a device to redirect its process)
        if self._current_device_obj() is not None:
            if name == "process":
                self.current["process_chain"] = "process"
                return {"op": "enter.process", "chain": "process"}
            r = self._current_room_obj()
            if r is not None:
                ch = r.get("contents", {}).get(name)
                if ch and ch.get("type") == "chain" and ch.get("value_type") == "command":
                    self.current["process_chain"] = name
                    return {"op": "enter.process", "chain": name}
        elif name == "process":
            return {"error": "not in a device"}

        # enter a palace?
        if name in self.ast["palaces"]:
            self.current = {
                "palace": name, "wing": None, "room": None,
                "type_def": None, "instance": None, "bag": None, "device": None, "process_chain": None
            }
            return {"op": "enter.palace", "name": name}

        palace = self.current["palace"]
        if palace is None:
            return {"error": "no palace"}

        palace_obj = self.ast["palaces"][palace]

        # If inside a type_def, check for method devices in that type
        td = self._current_type_def_obj()
        if td is not None and td.get(name, {}).get("type") == "device":
            self.current.update({"device": name, "process_chain": None})
            return {"op": "enter.device", "name": name}

        # enter a type definition?
        if name in palace_obj.get("types", {}):
            self.current.update({"type_def": name, "device": None, "process_chain": None})
            return {"op": "enter.type_def", "name": name}

        # enter a wing?
        if name in palace_obj.get("wings", {}):
            self.current.update({"wing": name, "room": None, "bag": None,
                                 "device": None, "process_chain": None})
            return {"op": "enter.wing", "name": name}

        # enter an existing room? (current wing first, then palace-level)
        wing = self.current["wing"]
        wing_rooms = (palace_obj.get("wings", {}).get(wing, {}).get("rooms", {})
                      if wing else {})
        palace_rooms = palace_obj.get("rooms", {})

        if name in wing_rooms:
            self.current.update({"room": name, "bag": None, "device": None,
                                 "process_chain": None})
            return {"op": "enter.room", "name": name}

        if name in palace_rooms:
            self.current.update({"wing": None, "room": name, "bag": None,
                                 "device": None, "process_chain": None})
            return {"op": "enter.room", "name": name}

        # enter an existing device or user-type instance in the current room?
        r = self._current_room_obj()
        if r is not None and name in r.get("contents", {}):
            item = r["contents"][name]
            item_type = item.get("type")
            if item_type == "device":
                self.current.update({"device": name, "process_chain": None})
                return {"op": "enter.device", "name": name}
            if item_type not in _BUILTIN_TYPES and item_type is not None:
                self.current.update({"instance": name, "device": None,
                                     "process_chain": None})
                return {"op": "enter.instance", "name": name, "type": item_type}

        return {"error": f"cannot find {name!r}"}

    def _cmd_enter_typed(self, kind: str, name: str) -> Dict:
        kind = _KIND_NORMALIZE.get(kind.lower().strip(), kind.lower().strip())
        name = name.strip()

        if kind in VALUE_TYPES:
            return {"error": f"{kind!r} is a value type and cannot be entered"}

        # ── Structural navigation (unique context-reset semantics) ─────────
        if kind == "palace":
            if name in _BUILTIN_TYPES or name in VALUE_TYPES:
                return {"error": f"{name!r} is a built-in type name"}
            self._ensure_palace(name)
            self._ensure_room(name, "lobby")
            self.current = {
                "palace": name, "wing": None, "room": "lobby",
                "type_def": None, "instance": None, "bag": None, "device": None, "process_chain": None
            }
            return {"op": "enter.palace", "name": name}

        palace = self.current["palace"]
        if palace is None:
            return {"error": "no palace"}

        if kind == "wing":
            if name in self._all_type_names(palace):
                return {"error": f"{name!r} is a type name"}
            self._ensure_wing(palace, name)
            self.current.update({"wing": name, "room": None, "type_def": None,
                                 "instance": None, "bag": None, "device": None, "process_chain": None})
            return {"op": "enter.wing", "name": name}

        if kind == "room":
            if name in self._all_type_names(palace):
                return {"error": f"{name!r} is a type name"}
            self._ensure_room(palace, name, self.current["wing"])
            self.current.update({"room": name, "type_def": None,
                                 "instance": None, "bag": None, "device": None, "process_chain": None})
            return {"op": "enter.room", "name": name}

        # ── Type definition ────────────────────────────────────────────────
        if kind == "type_def":
            palace_obj = self.ast["palaces"][palace]
            palace_obj.setdefault("types", {}).setdefault(name, _default("type_def"))
            self.current.update({"type_def": name, "instance": None,
                                 "device": None, "process_chain": None})
            return {"op": "enter.type_def", "name": name}

        # ── Device (special: can live in room or type_def) ─────────────────
        if kind == "device":
            res = self._cmd_device(name)
            if "error" not in res:
                res["op"] = "enter.device"
            return res

        # ── Bag (enter creates+navigates into bag context) ─────────────────
        if kind == "bag":
            r = self._current_room_obj()
            if r is None:
                return {"error": "no room"}
            err = self._check_room_item_name(r, name, "bag")
            if err:
                return err
            r["contents"].setdefault(name, _default("bag"))
            self.current.update({"bag": name, "instance": None,
                                 "device": None, "process_chain": None})
            return {"op": "enter.bag", "name": name}

        # ── Generic room-content builtins (chain, box, …) ─────────────────
        if kind in _ROOM_CONTENT_TYPES:
            r = self._current_room_obj()
            if r is None:
                return {"error": "no room"}
            err = self._check_room_item_name(r, name, kind)
            if err:
                return err
            r["contents"].setdefault(name, _default(kind))
            return {"op": f"enter.{kind}", "name": name}

        # ── User-defined type instance ─────────────────────────────────────
        palace_obj = self.ast["palaces"][palace]
        if kind in palace_obj.get("types", {}):
            r = self._current_room_obj()
            if r is None:
                return {"error": "no room"}
            err = self._check_room_item_name(r, name, kind)
            if err:
                return err
            r["contents"].setdefault(name, {
                "type": kind,
                **self._resolve_inherited_fields(palace_obj, kind),
            })
            self.current.update({"instance": name, "device": None, "process_chain": None})
            return {"op": "enter.instance", "name": name, "type": kind}

        return {"error": f"cannot enter {kind!r}"}

    def load_palace(self, name: str, palace_data: dict):
        """Merge a loaded palace into the AST and navigate into it."""
        self.ast["palaces"][name] = palace_data
        self.current = {
            "palace": name, "wing": None, "room": None,
            "type_def": None, "instance": None, "bag": None, "device": None, "process_chain": None,
        }

    def _cmd_go_to(self, name: str) -> Dict:
        palace = self.current["palace"]
        if palace is None:
            # Already loaded in a previous session?
            if name in self.ast.get("palaces", {}):
                self.current = {
                    "palace": name, "wing": None, "room": None,
                    "type_def": None, "instance": None, "bag": None, "device": None, "process_chain": None,
                }
                return {"op": "go.palace", "name": name}
            # Ask main.py to try loading from disk
            return {"op": "load.palace", "name": name}
        palace_obj = self.ast["palaces"][palace]

        # check palace-level rooms
        if name in palace_obj.get("rooms", {}):
            self.current.update({"wing": None, "room": name, "bag": None,
                                 "device": None, "process_chain": None})
            return {"op": "go.room", "name": name}

        # check all wings' rooms
        for wing_name, wing_obj in palace_obj.get("wings", {}).items():
            if name in wing_obj.get("rooms", {}):
                self.current.update({"wing": wing_name, "room": name, "bag": None,
                                     "device": None, "process_chain": None})
                return {"op": "go.room", "name": name}

        return {"error": f"no room {name}"}

    def _cmd_go_outside(self) -> Dict:
        self.current = {
            "palace": None, "wing": None, "room": None,
            "type_def": None, "instance": None, "bag": None, "device": None, "process_chain": None
        }
        return {"op": "go.outside"}

    def _cmd_exit(self) -> Dict:
        if self.current["process_chain"] is not None:
            self.current["process_chain"] = None
            return {"op": "exit.process"}
        if self.current["device"] is not None:
            self.current["device"] = None
            return {"op": "exit.device"}
        if self.current["instance"] is not None:
            self.current["instance"] = None
            return {"op": "exit.instance"}
        if self.current.get("bag") is not None:
            self.current["bag"] = None
            return {"op": "exit.bag"}
        if self.current["type_def"] is not None:
            self.current["type_def"] = None
            return {"op": "exit.type_def"}
        if self.current["room"] is not None:
            self.current["room"] = None
            return {"op": "exit.room"}
        if self.current["wing"] is not None:
            self.current["wing"] = None
            return {"op": "exit.wing"}
        if self.current["palace"] is not None:
            self.current["palace"] = None
            return {"op": "exit.palace"}
        return {"op": "exit"}

    def _cmd_delete(self, spec: str) -> Dict:
        """Delete anything reachable by a possessive path or 'CHAIN link N' spec."""
        if self.current["palace"] is None:
            return {"error": "no palace"}
        spec = self._strip_stop(spec.strip())
        targets = self._path_find_delete_targets(spec)
        if not targets:
            return {"error": f"cannot find {spec!r}"}
        if len(targets) > 1:
            return {"error": f"ambiguous: {spec!r}"}
        parent, key, action = targets[0]
        if action == "null":
            parent[key] = None
        elif action == "pop":
            parent.pop(key)   # list.pop(int_index)
        else:
            del parent[key]
        return {"op": "delete", "spec": spec}

    def _path_find_delete_targets(self, expr: str) -> List:
        """Return [(parent, key, action)] for every valid deletion target for expr.

        action: "null"   → set parent[key] = None
                "remove" → del parent[key]   (dict)
                "pop"    → parent.pop(key)   (list, key is int index)
        """
        expr = self._strip_stop(expr.strip())
        segs = expr.split(" 's ")
        seen: set = set()
        results: List = []

        def add(t) -> None:
            ident = (id(t[0]), t[1])
            if ident not in seen:
                seen.add(ident)
                results.append(t)

        for start in self._path_starting_contexts():
            for t in self._path_resolve_delete_from(start, segs):
                add(t)

        return results

    def _path_resolve_delete_from(self, obj: Dict, segs: List[str]) -> List:
        """Recursively resolve deletion path segments from obj."""
        if not segs:
            return []

        seg_words = segs[0].strip().split()
        remaining_segs = segs[1:]
        results: List = []

        for name_len in range(len(seg_words), 0, -1):
            name = " ".join(seg_words[:name_len])
            suffix = seg_words[name_len:]

            if suffix:
                if remaining_segs:
                    new_rem = [" ".join(suffix) + " " + remaining_segs[0]] + remaining_segs[1:]
                else:
                    new_rem = [" ".join(suffix)]
            else:
                new_rem = remaining_segs

            if not new_rem:
                t = self._path_terminal_delete(obj, name)
                if t is not None:
                    results.append(t)
            else:
                child = self._path_nav(obj, name)
                if child is not None:
                    results.extend(self._path_resolve_delete_from(child, new_rem))

        # "link N" — splice a chain link out of the links list
        if len(seg_words) >= 2 and seg_words[0] == "link":
            try:
                idx = int(seg_words[1])
                if obj.get("type") == "chain":
                    links = obj.get("links", [])
                    i0 = idx - 1
                    if 0 <= i0 < len(links):
                        suffix = seg_words[2:]
                        if not suffix and not remaining_segs:
                            results.append((links, i0, "pop"))
            except (ValueError, IndexError):
                pass

        return results

    # Properties that may be cleared (nulled) by delete — "name" and "type" are
    # structural identifiers and must never be deletable.
    _CLEARABLE_PROPS = frozenset({"value", "value_type", "comment"})

    def _path_terminal_delete(self, obj: Dict, name: str):
        """Return (parent, key, action) to delete 'name' on obj, or None if not found."""
        if obj is None:
            return None
        ot = obj.get("type")

        # Only clearable mapped properties (not "name" — it's a protected identifier)
        mapped = _PROP_MAP.get(name)
        if mapped is not None and mapped in self._CLEARABLE_PROPS and mapped in obj:
            return (obj, mapped, "null")

        if ot == "room":
            contents = obj.get("contents", {})
            if name in contents:
                return (contents, name, "remove")
        elif ot == "device":
            boxes = obj.get("boxes", {})
            if name in boxes:
                return (boxes, name, "remove")
        elif ot == "box":
            if name in ("value", "value_type"):
                return (obj, name, "null")
        elif ot == "bag":
            data = obj.get("data", {})
            if name in data:
                return (data, name, "remove")
        elif ot == "type_def":
            if name not in _TYPE_DEF_RESERVED and name in obj:
                return (obj, name, "remove")
        elif ot is not None and ot not in _BUILTIN_TYPES:
            if name != "type" and name in obj:
                return (obj, name, "remove")

        return None

    def _cmd_rename(self, old: str, new: str) -> Dict:
        old = self._strip_stop(old.strip())
        new = self._strip_stop(new.strip())
        if old == new:
            return {"op": "rename", "old": old, "new": new}

        palace = self.current["palace"]
        if palace is None:
            return {"error": "no palace"}
        palace_obj = self.ast["palaces"][palace]

        # ── 1. Room contents (box, chain, bag, device, instance) ──────────
        r = self._current_room_obj()
        if r is not None:
            contents = r.get("contents", {})
            if old in contents:
                if new in contents:
                    return {"error": f"name {new!r} is already in use in this room"}
                if new in self._all_type_names(palace):
                    return {"error": f"{new!r} is a type name"}
                contents[new] = contents.pop(old)
                if self.current.get("device") == old:
                    self.current["device"] = new
                if self.current.get("instance") == old:
                    self.current["instance"] = new
                return {"op": "rename", "old": old, "new": new}

        # ── 2. Type_def members (when inside a type) ──────────────────────
        td = self._current_type_def_obj()
        if td is not None:
            if old not in _TYPE_DEF_RESERVED and old in td:
                if new in td and new not in _TYPE_DEF_RESERVED:
                    return {"error": f"name {new!r} is already in use in this type"}
                member = td.pop(old)
                td[new] = member
                if member.get("type") == "device" and self.current.get("device") == old:
                    self.current["device"] = new
                return {"op": "rename", "old": old, "new": new}

        # ── 3. Rooms ───────────────────────────────────────────────────────
        wing = self.current["wing"]
        rooms = (palace_obj.get("wings", {}).get(wing, {}).get("rooms", {})
                 if wing else palace_obj.get("rooms", {}))
        if old in rooms:
            if new in self._all_type_names(palace):
                return {"error": f"{new!r} is a type name"}
            if new in rooms:
                return {"error": f"room {new!r} already exists"}
            rooms[new] = rooms.pop(old)
            if self.current.get("room") == old:
                self.current["room"] = new
            return {"op": "rename", "old": old, "new": new}

        # ── 4. Wings ───────────────────────────────────────────────────────
        wings = palace_obj.get("wings", {})
        if old in wings:
            if new in self._all_type_names(palace):
                return {"error": f"{new!r} is a type name"}
            if new in wings:
                return {"error": f"wing {new!r} already exists"}
            wings[new] = wings.pop(old)
            if self.current.get("wing") == old:
                self.current["wing"] = new
            return {"op": "rename", "old": old, "new": new}

        # ── 5. Types ───────────────────────────────────────────────────────
        types = palace_obj.get("types", {})
        if old in types:
            err = self._check_type_create_name(new)
            if err:
                return err
            if new in types:
                return {"error": f"type {new!r} already exists"}
            types[new] = types.pop(old)
            if self.current.get("type_def") == old:
                self.current["type_def"] = new
            return {"op": "rename", "old": old, "new": new}

        return {"error": f"cannot find {old!r}"}

    def _cmd_wing(self, name: str) -> Dict:
        palace = self.current["palace"]
        if palace is None:
            return {"error": "no palace"}
        if name in self._all_type_names(palace):
            return {"error": f"{name!r} is a type name"}
        self._ensure_wing(palace, name)
        return {"op": "wing.create", "name": name}

    def _cmd_room(self, name: str) -> Dict:
        palace = self.current["palace"]
        if palace is None:
            return {"error": "no palace"}
        if name in self._all_type_names(palace):
            return {"error": f"{name!r} is a type name"}
        self._ensure_room(palace, name, self.current["wing"])
        return {"op": "room.create", "name": name}

    def _eval_arith(self, s: str):
        """Evaluate a pure Palace arithmetic expression.  No variable lookup.
        Raises ValueError if the string cannot be fully parsed as an expression.
        Operator precedence (low → high): comparison < plus/minus < times/divided by
        < squared/cubed.  Minus is left-associative via rsplit.
        """
        s = s.strip()
        # comparisons (lowest precedence)
        for op_str, fn in [
            ("is less than",   lambda a, b: a < b),
            ("is greater than", lambda a, b: a > b),
            ("is equal to",    lambda a, b: a == b),
        ]:
            if f" {op_str} " in s:
                left, right = s.split(f" {op_str} ", 1)
                return fn(self._eval_arith(left), self._eval_arith(right))
        # addition
        if " plus " in s:
            return sum(self._eval_arith(p) for p in s.split(" plus "))
        # subtraction — rsplit gives left-associativity: a-b-c = (a-b)-c
        if " minus " in s:
            left, right = s.rsplit(" minus ", 1)
            return self._eval_arith(left) - self._eval_arith(right)
        # multiplication
        if " times " in s:
            result = 1
            for p in s.split(" times "):
                result *= self._eval_arith(p)
            return result
        # division
        if " divided by " in s:
            left, right = s.split(" divided by ", 1)
            denom = self._eval_arith(right)
            if denom == 0:
                raise ZeroDivisionError("division by zero")
            return self._eval_arith(left) / denom
        # postfix powers (highest arithmetic precedence)
        if s.endswith(" squared"):
            return self._eval_arith(s[:-8]) ** 2
        if s.endswith(" cubed"):
            return self._eval_arith(s[:-6]) ** 3
        # literals
        try:
            return int(s)
        except ValueError:
            pass
        try:
            return float(s)
        except ValueError:
            pass
        if s.lower() == "true":
            return True
        if s.lower() == "false":
            return False
        raise ValueError(f"not an expression: {s!r}")

    def _normalize_type(self, s: str) -> str:
        """Accept plural forms like 'numbers' → 'number'."""
        if s in VALUE_TYPES:
            return s
        if s.endswith("s") and s[:-1] in VALUE_TYPES:
            return s[:-1]
        return s


    def _cmd_chain(self, name: str, btype: str = None) -> Dict:
        palace = self.current["palace"]
        if palace is None:
            return {"error": "no palace"}
        room = self.current["room"]
        if room is None:
            return {"error": "chain must be in a room"}
        name = self._strip_stop(name.strip())
        if btype is not None:
            btype = self._normalize_type(btype)
            if btype not in VALUE_TYPES and btype != "command":
                return {"error": f"unknown type {btype!r}"}
        r = self._ensure_room(palace, room, self.current["wing"])
        err = self._check_room_item_name(r, name, "chain")
        if err:
            return err
        ch = r["contents"].setdefault(name, _default("chain"))
        if btype is not None:
            ch["value_type"] = btype
        self._last_link_chain = name
        result: Dict = {"op": "chain.create", "name": name}
        if btype is not None:
            result["value_type"] = btype
        return result

    def _cmd_bag(self, name: str, btype: str = None) -> Dict:
        palace = self.current["palace"]
        room = self.current["room"]
        if palace is None:
            return {"error": "no palace"}
        if room is None:
            return {"error": "bag must be in a room"}
        name = self._strip_stop(name.strip())
        if btype is not None:
            btype = self._normalize_type(btype)
            if btype not in VALUE_TYPES:
                return {"error": f"unknown type {btype!r} — valid types: {', '.join(VALUE_TYPES)}"}
        r = self._ensure_room(palace, room, self.current["wing"])
        err = self._check_room_item_name(r, name, "bag")
        if err:
            return err
        bg = r["contents"].setdefault(name, _default("bag"))
        if btype is not None:
            bg["value_type"] = btype
        result: Dict = {"op": "bag.create", "name": name}
        if btype is not None:
            result["value_type"] = btype
        return result

    def _cmd_create_device(self, name: str) -> Dict:
        palace = self.current["palace"]
        if palace is None:
            return {"error": "no palace"}
        td = self._current_type_def_obj()
        if td is not None:
            td.setdefault(name, _default("device"))
            return {"op": "device.create", "name": name}
        r = self._current_room_obj()
        err = self._check_room_item_name(r, name, "device")
        if err:
            return err
        r["contents"].setdefault(name, _default("device"))
        return {"op": "device.create", "name": name}

    def _type_of_value(self, v: Any) -> str:
        if isinstance(v, bool):
            return "boolean"
        if isinstance(v, (int, float)):
            return "number"
        if isinstance(v, str):
            return "string"
        return "unknown"

    def _check_box_type(self, entry: Dict, v: Any) -> Optional[str]:
        btype = entry.get("value_type")
        if btype is None:
            return None
        vtype = self._type_of_value(v)
        if vtype != btype:
            return f"cannot set box of type {btype} to {vtype} value"
        return None

    def _is_subtype_of(self, palace_obj: Dict, child: Optional[str], ancestor: str) -> bool:
        """Return True if child is ancestor or inherits from ancestor (cycle-safe)."""
        if child is None:
            return False
        if child == ancestor:
            return True
        types = palace_obj.get("types", {})
        visited: set = set()
        t = child
        while t and t in types and t not in visited:
            visited.add(t)
            t = types[t].get("parent")
            if t == ancestor:
                return True
        return False

    def _all_type_names(self, palace: str) -> frozenset:
        """All reserved type names: built-ins + value types + user-defined types."""
        user = set(self.ast["palaces"].get(palace, {}).get("types", {}).keys())
        return _BUILTIN_TYPES | frozenset(VALUE_TYPES) | user

    def _check_room_item_name(self, room_obj: Dict, name: str,
                               new_type: str) -> Optional[Dict]:
        """Return error dict if name is unusable for a new item of new_type in room_obj.

        Checks:
          1. name is not a reserved type name
          2. name is not already occupied by a different type in this room
        Returns None if the name is clear (or already occupied by same type, idempotent).
        """
        palace = self.current["palace"]
        if palace and name in self._all_type_names(palace):
            return {"error": f"{name!r} is a type name and cannot be used as an item name"}
        existing = room_obj.get("contents", {}).get(name)
        if existing is not None and existing.get("type") != new_type:
            return {"error": f"name {name!r} is already used as a "
                             f"{existing.get('type')} in this room"}
        return None

    def _check_type_create_name(self, name: str) -> Optional[Dict]:
        """Return error dict if name is unusable for a new type definition.

        Checks:
          1. name is not a built-in type or value type
          2. name is not used as an item in any room of the current palace
        """
        palace = self.current["palace"]
        if name in _BUILTIN_TYPES or name in VALUE_TYPES:
            return {"error": f"{name!r} is a built-in type name"}
        if palace:
            palace_obj = self.ast["palaces"].get(palace, {})
            for room_obj in palace_obj.get("rooms", {}).values():
                if name in room_obj.get("contents", {}):
                    return {"error": f"{name!r} is already used as a room item"}
            for wing_obj in palace_obj.get("wings", {}).values():
                for room_obj in wing_obj.get("rooms", {}).values():
                    if name in room_obj.get("contents", {}):
                        return {"error": f"{name!r} is already used as a room item"}
        return None

    def _current_bag_obj(self) -> Optional[Dict]:
        bag = self.current.get("bag")
        if bag is None:
            return None
        r = self._current_room_obj()
        if r is None:
            return None
        return r.get("contents", {}).get(bag)

    def _place_box(self, name: str, entry: Dict) -> str:
        """Insert box entry at current scope; return 'device', 'bag', or 'room'."""
        d = self._current_device_obj()
        if d is not None:
            d.setdefault("boxes", {})[name] = entry
            return "device"
        bg = self._current_bag_obj()
        if bg is not None:
            bg.setdefault("data", {})[name] = entry
            return "bag"
        r = self._current_room_obj()
        r.setdefault("contents", {})[name] = entry
        return "room"

    def _cmd_box_typed(self, btype: str, name: str = None) -> Dict:
        btype = self._normalize_type(btype)
        if self._current_room_obj() is None:
            return {"error": "no room"}
        if name is not None:
            name = self._strip_stop(name.strip())
            r = self._current_room_obj()
            if r is not None and self._current_device_obj() is None:
                err = self._check_room_item_name(r, name, "box")
                if err:
                    return err
        else:
            name = f"_box_{self._box_counter}"
            self._box_counter += 1
        scope = self._place_box(name, {"type": "box", "value": None, "value_type": btype})
        self._last_box = name
        return {"op": "box.create", "name": name, "value_type": btype, "scope": scope}

    def _cmd_set(self, lhs: str, rhs: str) -> Dict:
        """Generalized 'set LHS to RHS' — supports arbitrary possessive-path depth.

        LHS is resolved as a possessive path against the current AST context.
        Explicit structural prefixes bypass path resolution for clarity:
          - "box of TYPE [NAME]"  → typed box create-and-set
          - "box NAME [stop]"     → box create-if-needed and set value
          - "chain NAME [stop]"   → chain literal set
        Everything else is resolved via _path_find_targets, which handles
        chains of possessives of any length and auto-disambiguates by checking
        which paths actually exist in the AST.
        """
        lhs = lhs.strip()
        rhs = rhs.strip()
        words = lhs.split()

        # "box of TYPE [NAME [stop]]"
        if len(words) >= 3 and words[0] == "box" and words[1] == "of":
            btype = words[2]
            rest = words[3:]
            name = self._strip_stop(" ".join(rest)) if rest else None
            if not name:
                return self._cmd_set_box_typed(btype, rhs)
            return self._cmd_set_box_typed_named(btype, name, rhs)

        # "box NAME [stop]"
        if words and words[0] == "box":
            return self._cmd_set_box_value_named(self._strip_stop(" ".join(words[1:])), rhs)

        # "chain NAME [stop]"
        if words and words[0] == "chain":
            return self._cmd_set_chain_literal(self._strip_stop(" ".join(words[1:])), rhs)

        # General recursive path resolution
        targets = self._path_find_targets(lhs)
        if not targets:
            return self._path_error(lhs)
        if len(targets) > 1:
            # Multiple valid parses — report ambiguity rather than silently picking one
            paths = "; ".join(f"({id(c)}, {k!r})" for c, k in targets)
            return {"error": f"ambiguous path {lhs!r} — {len(targets)} interpretations exist",
                    "ambiguous": True}
        return self._path_apply(targets[0], rhs)

    # ------------------------------------------------------------------
    # Possessive-path resolution helpers
    # ------------------------------------------------------------------

    def _path_find_targets(self, expr: str) -> List[Tuple[Dict, str]]:
        """Find all valid (container, key) targets for a possessive-path expression.

        Splits expr on ' 's ' and walks the AST recursively, trying all
        possible multi-word-name splits within each segment.  Returns every
        valid terminal (container, key) pair found across all starting contexts.
        """
        expr = self._strip_stop(expr.strip())
        segs = expr.split(" 's ")

        seen: set = set()
        results: List[Tuple[Dict, str]] = []

        def add(c: Dict, k: str) -> None:
            ident = (id(c), k)
            if ident not in seen:
                seen.add(ident)
                results.append((c, k))

        for start in self._path_starting_contexts():
            for c, k in self._path_resolve_from(start, segs):
                add(c, k)

        return results

    def _path_starting_contexts(self) -> List[Dict]:
        """Return AST objects to use as path-resolution roots (most-specific first)."""
        starts: List[Dict] = []
        d = self._current_device_obj()
        if d is not None:
            starts.append(d)
        # current instance (when entered via 'enter NAME')
        inst_name = self.current.get("instance")
        if inst_name is not None:
            r = self._current_room_obj()
            if r is not None:
                inst = r.get("contents", {}).get(inst_name)
                if inst is not None:
                    starts.append(inst)
        r = self._current_room_obj()
        if r is not None:
            starts.append(r)
        td = self._current_type_def_obj()
        if td is not None and td not in starts:
            starts.append(td)
        p = self.current.get("palace")
        if p is not None:
            pobj = self.ast["palaces"].get(p)
            if pobj is not None:
                starts.append(pobj)
        return starts

    def _path_resolve_from(self, obj: Dict,
                           segs: List[str]) -> List[Tuple[Dict, str]]:
        """Recursively resolve path segments starting from obj.

        Each element of segs is a string of words (the text between successive
        ' 's ' markers in the original expression).  Within a segment the words
        can be split at any word boundary: the longest prefix that navigates to
        a real AST node wins (longest-first to prefer specific multi-word names),
        with shorter prefixes tried as fallback to allow ambiguity detection.
        """
        if not segs:
            return []

        seg_words = segs[0].strip().split()
        remaining_segs = segs[1:]
        results: List[Tuple[Dict, str]] = []

        # Try all prefix lengths within this segment (longest first)
        for name_len in range(len(seg_words), 0, -1):
            name = " ".join(seg_words[:name_len])
            suffix = seg_words[name_len:]

            # Suffix words fold back into the next segment
            if suffix:
                if remaining_segs:
                    new_rem = [" ".join(suffix) + " " + remaining_segs[0]] + remaining_segs[1:]
                else:
                    new_rem = [" ".join(suffix)]
            else:
                new_rem = remaining_segs

            if not new_rem:
                # Terminal: resolve (container, key) for setting 'name' on obj
                c, k = self._path_terminal(obj, name)
                if c is not None:
                    results.append((c, k))
            else:
                # Navigation: go into obj[name], then continue
                child = self._path_nav(obj, name)
                if child is not None:
                    results.extend(self._path_resolve_from(child, new_rem))

        # "link N [...]" — navigate into chain link at 1-based index
        if len(seg_words) >= 2 and seg_words[0] == "link":
            try:
                idx = int(seg_words[1])
                link = self._path_get_link(obj, idx)
                if link is not None:
                    suffix = seg_words[2:]
                    if suffix:
                        new_rem = ([" ".join(suffix) + " " + remaining_segs[0]]
                                   + remaining_segs[1:] if remaining_segs
                                   else [" ".join(suffix)])
                    else:
                        new_rem = remaining_segs
                    if not new_rem:
                        results.append((link, "value"))
                    else:
                        results.extend(self._path_resolve_from(link, new_rem))
            except (ValueError, IndexError):
                pass

        return results

    def _path_nav(self, obj: Dict, name: str) -> Optional[Dict]:
        """Navigate from obj to a named immediate child."""
        if obj is None:
            return None
        ot = obj.get("type")
        if ot == "room":
            return obj.get("contents", {}).get(name)
        elif ot == "device":
            if name == "input":
                return obj.get("input")
            return obj.get("boxes", {}).get(name)
        elif ot == "palace":
            child = obj.get("rooms", {}).get(name)
            if child is not None:
                return child
            child = obj.get("wings", {}).get(name)
            if child is not None:
                return child
            return obj.get("types", {}).get(name)
        elif ot == "wing":
            return obj.get("rooms", {}).get(name)
        elif ot == "type_def":
            if name not in _TYPE_DEF_RESERVED:
                return obj.get(name)
        elif ot is not None and ot not in _BUILTIN_TYPES:
            # User-type instance: navigate into a field (flat structure)
            if name != "type" and name in obj:
                return obj[name]
        return None

    def _path_terminal(self, obj: Dict, name: str) -> Tuple[Optional[Dict], Optional[str]]:
        """Return (container, key) for setting 'name' as the terminal of a path.

        Returns (None, None) if the target doesn't exist or isn't settable.
        """
        if obj is None:
            return None, None
        ot = obj.get("type")

        # Known property map
        mapped = _PROP_MAP.get(name)
        if mapped is not None:
            return obj, mapped

        # "parent" is settable on any type_def
        if name == "parent" and ot == "type_def":
            return obj, "parent"

        if ot == "room":
            child = obj.get("contents", {}).get(name)
            if child is not None and child.get("type") == "box":
                return child, "value"

        elif ot == "device":
            boxes = obj.get("boxes", {})
            if name in boxes:
                return boxes[name], "value"

        elif ot == "box":
            if name in ("value", "value_type"):
                return obj, name

        elif ot == "type_def":
            if name not in _TYPE_DEF_RESERVED and name in obj:
                member = obj[name]
                if isinstance(member, dict) and member.get("type") != "device":
                    return member, "value"

        elif ot is not None and ot not in _BUILTIN_TYPES:
            # User-type instance: flat structure
            if name != "type" and name in obj and isinstance(obj[name], dict):
                return obj[name], "value"

        return None, None

    def _path_get_link(self, obj: Dict, idx: int) -> Optional[Dict]:
        """Return the link at 1-based index, auto-extending the chain if needed."""
        if obj is None or obj.get("type") != "chain":
            return None
        links = obj.setdefault("links", [])
        i = idx - 1
        while len(links) <= i:
            links.append({"value": None})
        return links[i]

    def _path_apply(self, target: Tuple[Dict, str], rhs: str) -> Dict:
        """Write a parsed RHS value into target (container, key) with type-checking."""
        container, key = target
        rhs = rhs.strip()

        if key == "value_type":
            v: Any = self._normalize_type(self._strip_stop(rhs))
        elif key in ("name", "comment", "parent"):
            v = self._strip_stop(rhs)
        else:
            v = self._parse_value(rhs)

        container[key] = v
        return {"op": "set.path", "key": key, "value": v}

    def _path_error(self, lhs: str) -> Dict:
        """Generate a context-appropriate error for a failed path resolution."""
        words = lhs.split()

        # Possessive path where owner exists but terminal property is unknown
        if " 's " in lhs:
            prop = lhs.split(" 's ")[-1].strip()
            prop = self._strip_stop(prop)
            if _PROP_MAP.get(prop) is None and prop != "parent":
                return {"error": f"unknown property {prop!r}"}

        # "NAME parent" — type doesn't exist
        if len(words) >= 2 and words[-1] == "parent":
            owner = " ".join(words[:-1])
            if owner.endswith(" 's"):
                owner = owner[:-3]
            elif owner.endswith("'s"):
                owner = owner[:-2]
            owner = self._strip_stop(owner.strip())
            return {"error": f"no type {owner!r}"}

        # Single-name: check if it exists but isn't settable
        name = self._strip_stop(lhs)
        obj = self._resolve_owner(name)
        if obj is not None:
            return {"error": f"{name!r} is not a box"}

        return {"error": f"cannot find {name!r}"}

    def _cmd_set_box_value(self, name: str, value: str) -> Dict:
        """Sugar: 'set NAME to VALUE' → set NAME's value to VALUE (when NAME is a box)."""
        obj = self._resolve_owner(name)
        if obj is None:
            return {"error": f"cannot find {name!r}"}
        if obj.get("type") != "box":
            return {"error": f"{name!r} is not a box"}
        return self._cmd_set_possessive(name, "value", value)

    def _cmd_set_box_value_named(self, name: str, value: str) -> Dict:
        """Sugar: 'set box NAME (stop) to VALUE' → create box if needed, then set value."""
        name = self._strip_stop(name.strip())
        obj = self._resolve_owner(name)
        if obj is None:
            self._cmd_box(name)
        elif obj.get("type") != "box":
            return {"error": f"{name!r} is not a box"}
        return self._cmd_set_possessive(name, "value", value)

    def _cmd_set_box_typed_named(self, btype: str, name: str, value: str) -> Dict:
        """'set box of TYPE NAME to VALUE' → create typed box if needed, then set value."""
        res = self._cmd_box_typed(btype=btype, name=name)
        if "error" in res:
            return res
        return self._cmd_set_possessive(res["name"], "value", value)

    def _cmd_set_box_typed(self, btype: str, value: str) -> Dict:
        if btype not in VALUE_TYPES:
            return {"error": f"unknown type {btype!r} — valid types: {', '.join(VALUE_TYPES)}"}
        v = self._parse_value(value)
        err = self._check_box_type({"value_type": btype}, v)
        if err:
            return {"error": err}
        if self._current_room_obj() is None:
            return {"error": "no room"}
        name = f"_box_{self._box_counter}"
        self._box_counter += 1
        scope = self._place_box(name, {"type": "box", "value": v, "value_type": btype})
        self._last_box = name
        return {"op": "box.set", "name": name, "value_type": btype, "value": v,
                "scope": scope}

    def _cmd_box(self, name: str) -> Dict:
        # If in a type_def (but not in a method device), create a field
        td = self._current_type_def_obj()
        if td is not None and self.current["device"] is None:
            td.setdefault(name, {"type": "box", "value": None, "value_type": None})
            return {"op": "field.create", "name": name, "scope": "type"}
        d = self._current_device_obj()
        if d is not None:
            d.setdefault("boxes", {})[name] = {"type": "box", "value": None}
            return {"op": "box.create", "name": name, "scope": "device"}
        r = self._current_room_obj()
        if r is None:
            return {"error": "no room"}
        err = self._check_room_item_name(r, name, "box")
        if err:
            return err
        r.setdefault("contents", {})[name] = {"type": "box", "value": None}
        return {"op": "box.create", "name": name, "scope": "room"}

    def _cmd_append_link(self, chain: str) -> Dict:
        palace = self.current["palace"]
        if palace is None:
            return {"error": "no palace"}
        r = self._current_room_obj()
        err = self._check_room_item_name(r, chain, "chain")
        if err:
            return err
        ch = r["contents"].setdefault(chain, _default("chain"))
        ch["links"].append({"value": None})
        self._last_link_chain = chain
        return {"op": "chain.append_link", "chain": chain}

    def _cmd_append_to_chain(self, value: str, chain: str) -> Dict:
        palace = self.current["palace"]
        if palace is None:
            return {"error": "no palace"}
        r = self._current_room_obj()
        err = self._check_room_item_name(r, chain, "chain")
        if err:
            return err
        ch = r["contents"].setdefault(chain, _default("chain"))
        v = self._parse_value(value)
        # type check — explicit value_type takes precedence over inference
        chain_type = ch.get("value_type") or self._chain_type(ch)
        if chain_type is not None:
            v_type = ("boolean" if isinstance(v, bool)
                      else "number" if isinstance(v, (int, float))
                      else "string" if isinstance(v, str)
                      else None)
            if v_type and v_type != chain_type:
                return {"error":
                        f"cannot append {v_type} to chain of type {chain_type}"}
        ch["links"].append({"value": v})
        self._last_link_chain = chain
        return {"op": "chain.append", "chain": chain, "value": v}

    def _cmd_set_link_value(self, value: str) -> Dict:
        palace = self.current["palace"]
        if palace is None:
            return {"error": "no palace"}
        chain = self._last_link_chain
        if chain is None:
            return {"error": "no recent chain link to set"}
        r = self._current_room_obj()
        ch = r["contents"].get(chain)
        if not ch or ch.get("type") != "chain" or not ch["links"]:
            return {"error": f"no links in {chain}"}
        v = self._parse_value(value)
        ch["links"][-1]["value"] = v
        return {"op": "set.link.value", "chain": chain, "value": v}

    def _cmd_set_chain_literal(self, name: str, values: str) -> Dict:
        palace = self.current["palace"]
        room = self.current["room"]
        if palace is None:
            return {"error": "no palace"}
        if room is None:
            return {"error": "chain must be in a room"}
        name = self._strip_stop(name.strip())
        raw_parts = [v.strip() for v in values.split(" and ")]
        parsed = [self._parse_value(v) for v in raw_parts]
        # Infer value_type from the first non-None parsed value
        value_type = None
        for v in parsed:
            if isinstance(v, bool):
                value_type = "boolean"
                break
            if isinstance(v, (int, float)):
                value_type = "number"
                break
            if isinstance(v, str):
                value_type = "string"
                break
        r = self._ensure_room(palace, room, self.current["wing"])
        err = self._check_room_item_name(r, name, "chain")
        if err:
            return err
        ch = r["contents"].setdefault(name, _default("chain"))
        if value_type is not None:
            ch["value_type"] = value_type
        ch["links"] = [{"value": v} for v in parsed]
        self._last_link_chain = name
        return {"op": "chain.literal", "name": name,
                "value_type": value_type, "count": len(parsed)}

    def _cmd_set_chain_link(self, chain: str, idx: str, value: str) -> Dict:
        palace = self.current["palace"]
        if palace is None:
            return {"error": "no palace"}
        r = self._current_room_obj()
        ch = r["contents"].setdefault(chain, _default("chain"))
        i = int(idx) - 1      # 1-based → 0-based
        v = self._parse_value(value)
        while len(ch["links"]) <= i:
            ch["links"].append({"value": None})
        ch["links"][i]["value"] = v
        return {"op": "set.chain.link", "chain": chain, "index": i, "value": v}

    def _resolve_owner(self, name: str) -> Optional[Dict]:
        """Return the AST dict for a named item in the current context."""
        d = self._current_device_obj()
        if d is not None:
            if name == "input":
                return d.get("input")
            if name in d.get("boxes", {}):
                return d["boxes"][name]
        r = self._current_room_obj()
        if r is not None:
            contents = r.get("contents", {})
            if name in contents:
                return contents[name]
        return None

    def _cmd_set_possessive(self, owner: str, prop: str, value: str) -> Dict:
        prop = prop.strip().lower()
        field = _PROP_MAP.get(prop)
        if field is None:
            # Could be a user-type instance field (e.g. "set rect width to 5").
            # Only delegate if the owner is a user-type instance (not a built-in sub-object).
            if " " not in prop:
                r = self._current_room_obj()
                item = r.get("contents", {}).get(owner) if r else None
                if item is not None and item.get("type") not in _BUILTIN_TYPES:
                    return self._cmd_set_instance_field(owner, prop, value)
            return {"error": f"unknown property {prop!r}"}
        obj = self._resolve_owner(owner)
        if obj is None:
            return {"error": f"cannot find {owner!r}"}
        obj_type = obj.get("type")
        if obj_type and field in _STRUCTURAL_KEYS.get(obj_type, frozenset()):
            return {"error": f"cannot modify structural field {field!r} of {obj_type}"}
        if field == "value_type":
            v = self._normalize_type(self._strip_stop(value.strip()))
        elif field in ("name", "comment"):
            v = self._strip_stop(value.strip())
        else:
            v = self._parse_value(value)
        obj[field] = v
        return {"op": "set.possessive", "owner": owner, "field": field, "value": v}

    def _cmd_set_input(self, prop: str, value: str) -> Dict:
        d = self._current_device_obj()
        if d is None:
            return {"error": "not in a device"}
        value = self._strip_stop(value.strip())
        if prop == "name":
            d.setdefault("input", {})["name"] = value
            return {"op": "set.input.name", "value": value}
        else:  # type
            d.setdefault("input", {})["value_type"] = self._normalize_type(value)
            return {"op": "set.input.type", "value": value}

    def _cmd_set_comment(self, value: str) -> Dict:
        value = self._strip_stop(value.strip())
        # attach comment to the most specific current context
        d = self._current_device_obj()
        if d is not None:
            d["comment"] = value
        else:
            room = self._current_room_obj()
            if room is not None:
                room["comment"] = value
        return {"op": "set.comment", "value": value}

    def _step_to_command(self, body: str) -> Dict:
        """Convert a raw step body string into a structured command object."""
        s = body.strip()
        if s == "else":
            return {"type": "command", "operator": "else", "arguments": []}
        if s.startswith("return "):
            return {"type": "command", "operator": "return",
                    "arguments": [_parse_expr(s[7:].strip())]}
        if s.startswith("if "):
            return {"type": "command", "operator": "if",
                    "arguments": [_parse_expr(s[3:].strip())]}
        m = (re.match(r"^set new box (\w+) to (.+)$", s) or
             re.match(r"^set new box of (\w+) to (.+)$", s) or
             re.match(r"^set box (\w+) to (.+)$", s))
        if m:
            return {"type": "command", "operator": "set box",
                    "arguments": [m.group(1), _parse_expr(m.group(2).strip())]}
        m = re.match(r"^(\w+) link (.+) is (.+)$", s)
        if m:
            return {"type": "command", "operator": "link assign",
                    "arguments": [m.group(1),
                                  _parse_expr(m.group(2).strip()),
                                  _parse_expr(m.group(3).strip())]}
        # fallback: unrecognised body stored verbatim as operator
        return {"type": "command", "operator": s, "arguments": []}

    def _cmd_set_step(self, idx: str, body: str) -> Dict:
        d = self._current_device_obj()
        if d is None:
            return {"error": "not in a device"}
        body = self._strip_stop(body.strip())
        chain = self.current["process_chain"] or "process"
        i = int(idx) - 1
        if chain == "process":
            steps = d.setdefault("process", [])
            while len(steps) <= i:
                steps.append(None)
            steps[i] = self._step_to_command(body)
        else:
            r = self._current_room_obj()
            links = r["contents"][chain].setdefault("links", [])
            while len(links) <= i:
                links.append({"value": None})
            links[i] = {"value": body}
        return {"op": "device.set.step", "step": int(idx), "body": body}

    def _cmd_then(self, body: str) -> Dict:
        d = self._current_device_obj()
        if d is None:
            return {"error": "not in a device"}
        body = self._strip_stop(body.strip())
        chain = self.current["process_chain"] or "process"
        if chain == "process":
            d.setdefault("process", []).append(self._step_to_command(body))
        else:
            r = self._current_room_obj()
            r["contents"][chain].setdefault("links", []).append({"value": body})
        return {"op": "device.append.step", "body": body}

    def _cmd_device(self, name: str) -> Dict:
        palace = self.current["palace"]
        if palace is None:
            return {"error": "no palace"}
        # If in a type_def, create a method device
        td = self._current_type_def_obj()
        if td is not None:
            td.setdefault(name, _default("device"))
            self.current["device"] = name
            self.current["process_chain"] = None
            return {"op": "device.create", "name": name}
        r = self._current_room_obj()
        err = self._check_room_item_name(r, name, "device")
        if err:
            return err
        r["contents"].setdefault(name, _default("device"))
        self.current["device"] = name
        self.current["process_chain"] = None
        return {"op": "device.create", "name": name}

    # --- query handlers ---

    def _cmd_look_around(self) -> Dict:
        lines: List[str] = []

        palace   = self.current["palace"]
        wing     = self.current["wing"]
        room     = self.current["room"]
        type_def = self.current["type_def"]
        device   = self.current["device"]

        # ── location header ───────────────────────────────────────────────────
        if device is not None:
            location = f"device {device!r}"
            if room:    location += f" in room {room!r}"
            if wing:    location += f" in wing {wing!r}"
            if palace:  location += f" in palace {palace!r}"
        elif type_def is not None:
            location = f"type {type_def!r}"
            if palace:  location += f" in palace {palace!r}"
        elif room is not None:
            location = f"room {room!r}"
            if wing:    location += f" in wing {wing!r}"
            if palace:  location += f" in palace {palace!r}"
        elif wing is not None:
            location = f"wing {wing!r}"
            if palace:  location += f" in palace {palace!r}"
        elif palace is not None:
            location = f"palace {palace!r}"
        else:
            return {"op": "look.around", "description": "you are outside"}
        lines.append(f"You are in {location}.")

        # ── contents ──────────────────────────────────────────────────────────
        items: List[str] = []

        if device is not None:
            d = self._current_device_obj()
            if d:
                inp = d.get("input", {})
                inp_name = inp.get("name") or "input"
                inp_type = inp.get("value_type")
                if inp_type:
                    items.append(f"a box named {inp_name!r} (type {inp_type})")
                else:
                    items.append(f"a box named {inp_name!r}")
                steps = d.get("process", [])
                step_desc = f"{len(steps)} step{'s' if len(steps) != 1 else ''}"
                items.append(f"a chain named 'process' with {step_desc}")
                for bname, bobj in d.get("boxes", {}).items():
                    btype = bobj.get("value_type")
                    if btype:
                        items.append(f"a box named {bname!r} (type {btype})")
                    else:
                        items.append(f"a box named {bname!r}")
                if d.get("pattern"):
                    items.append(f"a pattern: {d['pattern']!r}")
                if d.get("comment"):
                    items.append(f"a comment: {d['comment']!r}")

        elif type_def is not None:
            td = self._current_type_def_obj()
            if td:
                for mname, mobj in td.items():
                    if mname in _TYPE_DEF_RESERVED or not isinstance(mobj, dict):
                        continue
                    if mobj.get("type") == "device":
                        items.append(f"a device named {mname!r}")
                    else:
                        ftype = mobj.get("value_type")
                        if ftype:
                            items.append(f"a box named {mname!r} (type {ftype})")
                        else:
                            items.append(f"a box named {mname!r}")

        elif room is not None:
            r = self._current_room_obj()
            if r:
                for cname, cobj in r.get("contents", {}).items():
                    ctype = cobj.get("type", "item")
                    items.append(f"a {ctype} named {cname!r}")

        elif palace is not None:
            p = self.ast["palaces"].get(palace, {})
            for rname in p.get("rooms", {}):
                items.append(f"a room named {rname!r}")
            for wname in p.get("wings", {}):
                items.append(f"a wing named {wname!r}")
            for tname in p.get("types", {}):
                items.append(f"a type named {tname!r}")

        if items:
            lines.append("You see: " + ", ".join(items) + ".")
        else:
            lines.append("You see nothing.")

        return {"op": "look.around", "description": " ".join(lines)}

    def _cmd_whereami(self) -> Dict:
        return {
            "op": "whereami",
            "palace": self.current["palace"],
            "wing": self.current["wing"],
            "room": self.current["room"],
            "device": self.current["device"],
        }

    def _cmd_step_length(self) -> Dict:
        d = self._current_device_obj()
        if d is None:
            return {"error": "not in a device"}
        return {"op": "query.step_length", "length": len(d.get("process", []))}

    def _cmd_query_link(self, chain: str, idx: str,
                        value_of: Optional[str] = None) -> Dict:
        palace = self.current["palace"]
        if palace is None:
            return {"error": "no palace"}
        r = self._current_room_obj()
        ch = r["contents"].get(chain)
        if ch is None or ch.get("type") != "chain":
            return {"error": f"no chain {chain}"}
        i = int(idx) - 1
        links = ch["links"]
        if i < 0 or i >= len(links):
            return {"error": f"link {idx} out of range"}
        val = links[i].get("value")
        next_name = (f"link {int(idx) + 1}" if i + 1 < len(links) else "none")
        desc = (f"link {idx} is a link with value {val}"
                f" and next link \"{next_name}\"")
        return {
            "op": "query.link",
            "chain": chain,
            "index": i,
            "value": val,
            "value_of": bool(value_of),
            "description": desc,
        }

    def _cmd_length(self, chain: str) -> Dict:
        palace = self.current["palace"]
        if palace is None:
            return {"error": "no palace"}
        r = self._current_room_obj()
        ch = r["contents"].get(chain)
        length = len(ch["links"]) if ch and ch.get("type") == "chain" else 0
        return {"op": "query.length", "chain": chain, "length": length}

    # --- run handlers ---

    def _cmd_run(self, device: str, value: Optional[str] = None) -> Dict:
        return {
            "op": "run",
            "palace": self.current["palace"],
            "room": self.current["room"] or "lobby",
            "device": device,
            "input": self._parse_value(value) if value is not None else None,
        }

    def _cmd_run_room(self, room: str, device: str,
                      value: Optional[str] = None) -> Dict:
        palace = self.current["palace"]
        # Check if 'room' is actually a user-type instance in the current room
        r = self._current_room_obj()
        if r is not None:
            item = r.get("contents", {}).get(room)
            if (item is not None and item.get("type") is not None
                    and item.get("type") not in _BUILTIN_TYPES):
                return {
                    "op": "run.instance",
                    "palace": palace,
                    "room_name": self.current["room"] or "lobby",
                    "instance": room,
                    "device": device,
                    "input": self._parse_value(value) if value is not None else None,
                }
        return {
            "op": "run",
            "palace": palace,
            "room": room,
            "device": device,
            "input": self._parse_value(value) if value is not None else None,
        }

    def _cmd_run_full(self, palace: str, room: str, device: str,
                      value: Optional[str] = None) -> Dict:
        return {
            "op": "run",
            "palace": palace,
            "room": room,
            "device": device,
            "input": self._parse_value(value) if value is not None else None,
        }

    # --- user-type command handlers ---

    def _cmd_type(self, name: str) -> Dict:
        palace = self.current["palace"]
        if palace is None:
            return {"error": "no palace"}
        err = self._check_type_create_name(name)
        if err:
            return err
        palace_obj = self.ast["palaces"][palace]
        palace_obj.setdefault("types", {}).setdefault(name, _default("type_def"))
        return {"op": "type.create", "name": name}

    def _cmd_type_from(self, name: str, parent: str) -> Dict:
        res = self._cmd_type(name)
        if "error" in res:
            return res
        palace = self.current["palace"]
        self.ast["palaces"][palace]["types"][name]["parent"] = parent
        res["parent"] = parent
        return res

    def _cmd_set_parent(self, name: str, parent: str) -> Dict:
        palace = self.current["palace"]
        if palace is None:
            return {"error": "no palace"}
        types = self.ast["palaces"][palace].get("types", {})
        if name not in types:
            return {"error": f"no type {name!r}"}
        types[name]["parent"] = parent
        return {"op": "set.parent", "name": name, "parent": parent}

    def _cmd_step_shorthand(self, idx: str, body: str) -> Dict:
        return self._cmd_set_step(idx, body)

    def _cmd_set_pattern(self, value: str) -> Dict:
        value = self._strip_stop(value.strip())
        d = self._current_device_obj()
        if d is None:
            return {"error": "not in a device"}
        d["pattern"] = value
        return {"op": "set.pattern", "value": value}

    def _resolve_inherited_fields(self, palace_obj: Dict, type_name: str) -> Dict:
        """Return merged fields for type_name, oldest ancestor first, child overrides last.

        Walks the parent chain, collects user-defined types only (stops at built-ins),
        then deep-copies each generation's fields from oldest to newest so child
        definitions overwrite ancestor definitions.  Cycle-safe.
        """
        types = palace_obj.get("types", {})
        chain: List[str] = []
        visited: set = set()
        t = type_name
        while t and t in types and t not in visited:
            visited.add(t)
            chain.append(t)
            t = types[t].get("parent")
        chain.reverse()   # oldest ancestor first
        merged: Dict = {}
        for ancestor in chain:
            for fname, fdef in types[ancestor].items():
                if fname in _TYPE_DEF_RESERVED or not isinstance(fdef, dict):
                    continue
                if fdef.get("type") == "device":
                    continue
                merged[fname] = copy.deepcopy(fdef)
        return merged

    def _cmd_instantiate(self, type_name: str, instance_name: str) -> Dict:
        palace = self.current["palace"]
        if palace is None:
            return {"error": "no palace"}
        palace_obj = self.ast["palaces"][palace]
        types = palace_obj.get("types", {})
        if type_name not in types:
            return {"error": f"unknown type {type_name!r}"}
        instance = {
            "type": type_name,
            **self._resolve_inherited_fields(palace_obj, type_name),
        }
        r = self._current_room_obj()
        if r is None:
            return {"error": "no room"}
        err = self._check_room_item_name(r, instance_name, type_name)
        if err:
            return err
        r["contents"][instance_name] = instance
        return {"op": "instance.create", "type": type_name, "name": instance_name}

    def _cmd_set_instance_field(self, instance: str, field: str, value: str) -> Dict:
        r = self._current_room_obj()
        if r is None:
            return {"error": "no room"}
        item = r.get("contents", {}).get(instance)
        if item is None:
            return {"error": f"cannot find {instance!r}"}
        type_name = item.get("type")
        if type_name in _BUILTIN_TYPES or type_name is None:
            return {"error": f"{instance!r} is not a user-type instance"}
        palace = self.current["palace"]
        palace_obj = self.ast["palaces"].get(palace, {})
        type_def = palace_obj.get("types", {}).get(type_name)
        if type_def is None:
            return {"error": f"type {type_name!r} not found"}
        if (field in _TYPE_DEF_RESERVED or field not in type_def
                or type_def[field].get("type") == "device"):
            return {"error": f"no field {field!r} on type {type_name!r}"}
        v = self._parse_value(value)
        item.setdefault(field, {"type": "box", "value": None})["value"] = v
        return {"op": "set.instance.field", "instance": instance, "field": field, "value": v}

    def _try_type_patterns(self, t: str) -> Optional[Dict]:
        """Check user-defined device patterns and return a run.instance action if matched."""
        palace = self.current["palace"]
        if palace is None:
            return None
        palace_obj = self.ast["palaces"].get(palace, {})
        for type_name, type_def in palace_obj.get("types", {}).items():
            for dev_name, dev in type_def.items():
                if dev_name in _TYPE_DEF_RESERVED or not isinstance(dev, dict):
                    continue
                if dev.get("type") != "device":
                    continue
                pattern_str = dev.get("pattern")
                if not isinstance(pattern_str, str):
                    continue
                # Convert "name" placeholder into a named capturing group
                parts = pattern_str.split("name")
                regex = r"(?P<instance>\w+)".join(re.escape(p) for p in parts)
                m = re.match(r"^" + regex + r"$", t, re.IGNORECASE)
                if m:
                    instance_name = m.group("instance")
                    room_obj = self._current_room_obj()
                    if room_obj is None:
                        continue
                    item = room_obj.get("contents", {}).get(instance_name)
                    if item is not None and self._is_subtype_of(palace_obj, item.get("type"), type_name):
                        return {
                            "op": "run.instance",
                            "palace": palace,
                            "room_name": self.current["room"] or "lobby",
                            "instance": instance_name,
                            "device": dev_name,
                            "input": None,
                        }
        return None
