import re
import json
import copy
import os
from typing import Any, Dict, List, Optional, Tuple

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

# Builtin type names — used to distinguish user-type instances from builtins.
_BUILTIN_TYPES = frozenset({
    "palace", "wing", "room", "device", "chain", "box", "bag", "type_def", "link"
})

# Maps action op prefixes to the kind of object whose name should be recorded
# in _last_by_type.  Checked in order; first prefix match wins.
_OP_TO_KIND: List[Tuple[str, str]] = [
    ("palace",      "palace"),
    ("enter.palace","palace"),
    ("enter.wing",  "wing"),
    ("wing",        "wing"),
    ("enter.room",  "room"),
    ("room",        "room"),
    ("enter.device","device"),
    ("device",      "device"),
    ("chain",       "chain"),
    ("bag",         "bag"),
    ("box",         "box"),
    ("enter.type",  "type"),
    ("type",        "type"),
    ("enter.instance", "instance"),
    ("instance",    "instance"),
]


class IDE:
    """Voice-command -> AST translator for Palace Language.

    Keeps a workspace in-memory and can dump it as JSON.
    Covers all commands in the canonical example session.
    """

    def __init__(self):
        self.ast: Dict[str, Any] = {"palaces": {}}
        self.current = {
            "palace": None, "wing": None, "room": None,
            "type_def": None, "instance": None, "device": None, "process_chain": None
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
            return td.get("devices", {}).get(dev)
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
    # Main dispatcher
    # ------------------------------------------------------------------

    def process(self, utterance: str) -> Dict[str, Any]:
        t = self._preprocess(utterance)

        patterns: List[Tuple[str, Any]] = [
            # --- Queries (most specific first) ---
            (r"^look around$", self._cmd_look_around),
            (r"^where am [Ii]\?*$", self._cmd_whereami),
            (r"^what is (?:the )?step length\??$", self._cmd_step_length),
            (r"^what is (?:the )?(?P<value_of>value of )?(?P<chain>\w+)(?:'s)? link (?P<idx>\d+)\??$",
             self._cmd_query_link),
            (r"^(?:what is (?:the )?)?length of (?P<chain>\w+)\??$",
             self._cmd_length),

            # --- Palace & navigation ---
            (r"^palace (?:called |named )?(?P<name>\w+)(?: stop)?$", self._cmd_palace),
            (r"^enter (?:new )?(?P<kind>\w+) (?P<name>.+?)(?: stop)?$",
             self._cmd_enter_typed),
            (r"^enter (?P<name>\w+)(?: stop)?$", self._cmd_enter),
            (r"^go to (?P<name>\w+)(?: stop)?$", self._cmd_go_to),
            (r"^go outside$", self._cmd_go_outside),
            (r"^exit$", self._cmd_exit),

            # --- Creation ---
            (r"^wing (?P<name>\w+)(?: stop)?$", self._cmd_wing),
            (r"^room (?P<name>\w+)(?: stop)?$", self._cmd_room),
            (r"^chain(?: of (?P<btype>\w+))? (?P<name>.+?)(?: stop)?$", self._cmd_chain),
            (r"^bag(?: of (?P<btype>\w+))? (?P<name>.+?)(?: stop)?$", self._cmd_bag),
            (r"^device (?P<name>\w+)(?: stop)?$", self._cmd_create_device),
            (r"^box (?P<name>\w+) of (?P<btype>\w+)(?: stop)?$", self._cmd_box_typed),
            (r"^box of (?P<btype>\w+)(?: (?P<name>.+?))?(?: stop)?$", self._cmd_box_typed),
            (r"^box (?P<name>.+?)(?: stop)?$", self._cmd_box),
            (r"^type (?P<name>\w+)(?: stop)?$", self._cmd_type),

            # --- Append ---
            (r"^append link to (?P<chain>\w+)(?: stop)?$", self._cmd_append_link),
            (r"^append (?P<value>.+) to (?P<chain>\w+)$",
             self._cmd_append_to_chain),

            # --- Set (specific → general) ---
            (r"^set box of (?P<btype>\w+) to (?P<value>.+)$",
             self._cmd_set_box_typed),
            (r"^set box (?P<name>.+?)(?: stop)? to (?P<value>.+)$",
             self._cmd_set_box_value_named),
            (r"^set (?P<chain>\w+)(?:'s)? link (?P<idx>\d+) to (?P<value>.+)$",
             self._cmd_set_chain_link),
            (r"^set link value (?:to )?(?P<value>.+)$",
             self._cmd_set_link_value),
            (r"^set input (?P<prop>name|type) to (?P<value>.+)$", self._cmd_set_input),
            (r"^set comment to (?P<value>.+)$", self._cmd_set_comment),
            (r"^set step (?P<idx>\d+) to (?P<body>.+)$", self._cmd_set_step),
            (r"^set pattern to (?P<value>.+)$", self._cmd_set_pattern),
            (r"^set chain (?P<name>.+?) to (?P<values>.+)$", self._cmd_set_chain_literal),
            (r"^set (?P<name>\w+) to (?P<value>.+)$", self._cmd_set_box_value),
            (r"^set (?P<owner>\w+)(?:'s)? (?P<prop>.+?) to (?P<value>.+)$",
             self._cmd_set_possessive),

            # --- Then (step-append sugar) ---
            (r"^then (?P<body>.+)$", self._cmd_then),
            (r"^step (?P<idx>\d+) (?P<body>.+)$", self._cmd_step_shorthand),

            # --- Run (3-level → 2-level → 1-level) ---
            (r"^run (?P<palace>\w+)'s? (?P<room>\w+)'s? (?P<device>\w+)"
             r"(?: on (?P<value>.+))?$", self._cmd_run_full),
            (r"^run (?P<room>\w+)'s? (?P<device>\w+)(?: on (?P<value>.+))?$",
             self._cmd_run_room),
            (r"^run (?P<device>\w+)(?: on (?P<value>.+))?$", self._cmd_run),
            (r"^(?P<type_name>[a-zA-Z]\w*) (?P<instance_name>[a-zA-Z]\w*)(?: stop)?$", self._cmd_instantiate),
        ]

        for pat, fn in patterns:
            m = re.match(pat, t, re.IGNORECASE)
            if m:
                res = fn(**m.groupdict())
                if isinstance(res, dict):
                    if "name" in res:
                        name = res["name"]
                        self._last_by_type["it"] = name
                        op = res.get("op", "")
                        for prefix, kind in _OP_TO_KIND:
                            if op.startswith(prefix):
                                self._last_by_type[kind] = name
                                # instance.create also records under its user type name
                                if kind == "instance" and "type" in res:
                                    self._last_by_type[res["type"]] = name
                                break
                    if "error" in res:
                        return {"ok": False, "error": res["error"]}
                return {"ok": True, "action": res}

        action = self._try_type_patterns(t)
        if action is not None:
            return {"ok": True, "action": action}

        # last resort: try as a raw arithmetic expression
        try:
            v = self._eval_arith(t)
            if isinstance(v, float) and v.is_integer():
                v = int(v)
            return {"ok": True, "action": {"op": "expr.result", "value": v}}
        except (ValueError, TypeError, ZeroDivisionError):
            pass
        return {"ok": False, "error": f"unrecognized: {t}"}

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
        self._ensure_palace(name)
        self._ensure_room(name, "lobby")   # every palace starts with lobby
        self.current = {
            "palace": name, "wing": None, "room": None,
            "type_def": None, "instance": None, "device": None, "process_chain": None
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
                "type_def": None, "instance": None, "device": None, "process_chain": None
            }
            return {"op": "enter.palace", "name": name}

        palace = self.current["palace"]
        if palace is None:
            return {"error": "no palace"}

        palace_obj = self.ast["palaces"][palace]

        # If inside a type_def, check for method devices in that type
        td = self._current_type_def_obj()
        if td is not None and name in td.get("devices", {}):
            self.current.update({"device": name, "process_chain": None})
            return {"op": "enter.device", "name": name}

        # enter a type definition?
        if name in palace_obj.get("types", {}):
            self.current.update({"type_def": name, "device": None, "process_chain": None})
            return {"op": "enter.type_def", "name": name}

        # enter a wing?
        if name in palace_obj.get("wings", {}):
            self.current.update({"wing": name, "room": None,
                                 "device": None, "process_chain": None})
            return {"op": "enter.wing", "name": name}

        # enter an existing room? (current wing first, then palace-level)
        wing = self.current["wing"]
        wing_rooms = (palace_obj.get("wings", {}).get(wing, {}).get("rooms", {})
                      if wing else {})
        palace_rooms = palace_obj.get("rooms", {})

        if name in wing_rooms:
            self.current.update({"room": name, "device": None,
                                 "process_chain": None})
            return {"op": "enter.room", "name": name}

        if name in palace_rooms:
            self.current.update({"wing": None, "room": name,
                                 "device": None, "process_chain": None})
            return {"op": "enter.room", "name": name}

        # enter an existing device in the current room?
        r = self._current_room_obj()
        if (r is not None and name in r.get("contents", {})
                and r["contents"][name].get("type") == "device"):
            self.current.update({"device": name, "process_chain": None})
            return {"op": "enter.device", "name": name}

        # implicitly create a new room (in current wing if any)
        self._ensure_room(palace, name, wing)
        self.current.update({"room": name, "device": None,
                             "process_chain": None})
        return {"op": "enter.room.create", "name": name}

    def _cmd_enter_typed(self, kind: str, name: str) -> Dict:
        kind = kind.lower()
        name = name.strip()

        if kind == "palace":
            self._ensure_palace(name)
            self._ensure_room(name, "lobby")
            self.current = {
                "palace": name, "wing": None, "room": "lobby",
                "type_def": None, "instance": None, "device": None, "process_chain": None
            }
            return {"op": "enter.palace", "name": name}

        palace = self.current["palace"]
        if palace is None:
            return {"error": "no palace"}

        if kind == "wing":
            self._ensure_wing(palace, name)
            self.current.update({"wing": name, "room": None, "type_def": None,
                                 "instance": None, "device": None, "process_chain": None})
            return {"op": "enter.wing", "name": name}

        if kind == "room":
            wing = self.current["wing"]
            self._ensure_room(palace, name, wing)
            self.current.update({"room": name, "type_def": None,
                                 "instance": None, "device": None, "process_chain": None})
            return {"op": "enter.room", "name": name}

        if kind == "device":
            return self._cmd_device(name)

        if kind == "type":
            palace_obj = self.ast["palaces"][palace]
            palace_obj.setdefault("types", {}).setdefault(name, _default("type_def"))
            self.current.update({"type_def": name, "instance": None,
                                 "device": None, "process_chain": None})
            return {"op": "enter.type_def", "name": name}

        # user-defined type instance
        palace_obj = self.ast["palaces"][palace]
        if kind in palace_obj.get("types", {}):
            r = self._current_room_obj()
            if r is None:
                return {"error": "no room"}
            type_def = palace_obj["types"][kind]
            r["contents"].setdefault(name, {
                "type": kind,
                "fields": copy.deepcopy(type_def.get("fields", {})),
            })
            self.current.update({"instance": name, "device": None, "process_chain": None})
            return {"op": "enter.instance", "name": name, "type": kind}

        return {"error": f"cannot enter {kind!r}"}

    def _cmd_go_to(self, name: str) -> Dict:
        palace = self.current["palace"]
        if palace is None:
            return {"error": "no palace"}
        palace_obj = self.ast["palaces"][palace]

        # check palace-level rooms
        if name in palace_obj.get("rooms", {}):
            self.current.update({"wing": None, "room": name,
                                 "device": None, "process_chain": None})
            return {"op": "go.room", "name": name}

        # check all wings' rooms
        for wing_name, wing_obj in palace_obj.get("wings", {}).items():
            if name in wing_obj.get("rooms", {}):
                self.current.update({"wing": wing_name, "room": name,
                                     "device": None, "process_chain": None})
                return {"op": "go.room", "name": name}

        return {"error": f"no room {name}"}

    def _cmd_go_outside(self) -> Dict:
        self.current = {
            "palace": None, "wing": None, "room": None,
            "type_def": None, "instance": None, "device": None, "process_chain": None
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

    def _cmd_wing(self, name: str) -> Dict:
        palace = self.current["palace"]
        if palace is None:
            return {"error": "no palace"}
        self._ensure_wing(palace, name)
        return {"op": "wing.create", "name": name}

    def _cmd_room(self, name: str) -> Dict:
        palace = self.current["palace"]
        if palace is None:
            return {"error": "no palace"}
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
        r = self._ensure_room(palace, room, self.current["wing"])
        ch = r["contents"].setdefault(name, _default("chain"))
        if btype is not None:
            btype = self._normalize_type(btype)
            if btype not in VALUE_TYPES and btype != "command":
                return {"error": f"unknown type {btype!r}"}
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
        r = self._ensure_room(palace, room, self.current["wing"])
        bg = r["contents"].setdefault(name, _default("bag"))
        if btype is not None:
            btype = self._normalize_type(btype)
            if btype not in VALUE_TYPES:
                return {"error": f"unknown type {btype!r} — valid types: {', '.join(VALUE_TYPES)}"}
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
            td["devices"].setdefault(name, _default("device"))
            return {"op": "device.create", "name": name}
        r = self._current_room_obj()
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

    def _place_box(self, name: str, entry: Dict) -> str:
        """Insert box entry at current scope; return 'device' or 'room'."""
        d = self._current_device_obj()
        if d is not None:
            d.setdefault("boxes", {})[name] = entry
            return "device"
        r = self._current_room_obj()
        r.setdefault("contents", {})[name] = entry
        return "room"

    def _cmd_box_typed(self, btype: str, name: str = None) -> Dict:
        btype = self._normalize_type(btype)
        if btype not in VALUE_TYPES:
            return {"error": f"unknown type {btype!r} — valid types: {', '.join(VALUE_TYPES)}"}
        if self._current_room_obj() is None:
            return {"error": "no room"}
        if name is not None:
            name = self._strip_stop(name.strip())
        else:
            name = f"_box_{self._box_counter}"
            self._box_counter += 1
        scope = self._place_box(name, {"type": "box", "value": None, "value_type": btype})
        self._last_box = name
        return {"op": "box.create", "name": name, "value_type": btype, "scope": scope}

    def _cmd_set_box_value(self, name: str, value: str) -> Dict:
        """Sugar: 'set NAME to VALUE' → set NAME's value to VALUE (when NAME is a box)."""
        obj = self._resolve_owner(name)
        if obj is None:
            return {"error": f"cannot find {name!r}"}
        if obj.get("type") != "box":
            return {"error": f"{name!r} is not a box"}
        return self._cmd_set_possessive(name, "value", value)

    def _cmd_set_box_value_named(self, name: str, value: str) -> Dict:
        """Sugar: 'set box NAME (stop) to VALUE' → set NAME's value to VALUE."""
        name = self._strip_stop(name.strip())
        obj = self._resolve_owner(name)
        if obj is None:
            return {"error": f"cannot find {name!r}"}
        if obj.get("type") != "box":
            return {"error": f"{name!r} is not a box"}
        return self._cmd_set_possessive(name, "value", value)

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
            td["fields"].setdefault(name, {"type": "box", "value": None, "value_type": None})
            return {"op": "field.create", "name": name, "scope": "type"}
        d = self._current_device_obj()
        if d is not None:
            d.setdefault("boxes", {})[name] = {"type": "box", "value": None}
            return {"op": "box.create", "name": name, "scope": "device"}
        r = self._current_room_obj()
        if r is None:
            return {"error": "no room"}
        r.setdefault("contents", {})[name] = {"type": "box", "value": None}
        return {"op": "box.create", "name": name, "scope": "room"}

    def _cmd_append_link(self, chain: str) -> Dict:
        palace = self.current["palace"]
        if palace is None:
            return {"error": "no palace"}
        r = self._current_room_obj()
        ch = r["contents"].setdefault(chain, _default("chain"))
        ch["links"].append({"value": None})
        self._last_link_chain = chain
        return {"op": "chain.append_link", "chain": chain}

    def _cmd_append_to_chain(self, value: str, chain: str) -> Dict:
        palace = self.current["palace"]
        if palace is None:
            return {"error": "no palace"}
        r = self._current_room_obj()
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
                steps.append("")
            steps[i] = body
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
            d.setdefault("process", []).append(body)
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
            td["devices"].setdefault(name, _default("device"))
            self.current["device"] = name
            self.current["process_chain"] = None
            return {"op": "device.create", "name": name}
        r = self._current_room_obj()
        r["contents"].setdefault(name, _default("device"))
        self.current["device"] = name
        self.current["process_chain"] = None
        return {"op": "device.create", "name": name}

    # --- query handlers ---

    def _cmd_look_around(self) -> Dict:
        items: List[tuple] = []

        if self.current["device"] is not None:
            # Inside a device: list its local boxes
            d = self._current_device_obj()
            if d:
                for bname in d.get("boxes", {}):
                    items.append(("box", bname))
        elif self.current["type_def"] is not None:
            # Inside a type definition: list fields and method devices
            td = self._current_type_def_obj()
            if td:
                for fname in td.get("fields", {}):
                    items.append(("box", fname))
                for dname in td.get("devices", {}):
                    items.append(("device", dname))
        elif self.current["room"] is not None:
            # Inside a room: list all contents
            r = self._current_room_obj()
            if r:
                for name, item in r.get("contents", {}).items():
                    items.append((item.get("type", "item"), name))
        elif self.current["palace"] is not None:
            # Palace level: list rooms and wings
            p = self.ast["palaces"].get(self.current["palace"], {})
            for rname in p.get("rooms", {}):
                items.append(("room", rname))
            for wname in p.get("wings", {}):
                items.append(("wing", wname))

        if not items:
            desc = "you see nothing"
        else:
            parts = [f"a {itype} named {iname}" for itype, iname in items]
            desc = "you see " + " stop and ".join(parts)
        return {"op": "look.around", "description": desc}

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
        palace_obj = self.ast["palaces"][palace]
        palace_obj.setdefault("types", {}).setdefault(name, _default("type_def"))
        return {"op": "type.create", "name": name}

    def _cmd_step_shorthand(self, idx: str, body: str) -> Dict:
        return self._cmd_set_step(idx, body)

    def _cmd_set_pattern(self, value: str) -> Dict:
        value = self._strip_stop(value.strip())
        d = self._current_device_obj()
        if d is None:
            return {"error": "not in a device"}
        d["pattern"] = value
        return {"op": "set.pattern", "value": value}

    def _cmd_instantiate(self, type_name: str, instance_name: str) -> Dict:
        palace = self.current["palace"]
        if palace is None:
            return {"error": "no palace"}
        palace_obj = self.ast["palaces"][palace]
        types = palace_obj.get("types", {})
        if type_name not in types:
            return {"error": f"unknown type {type_name!r}"}
        type_def = types[type_name]
        instance = {
            "type": type_name,
            "fields": copy.deepcopy(type_def.get("fields", {})),
        }
        r = self._current_room_obj()
        if r is None:
            return {"error": "no room"}
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
        if field not in type_def.get("fields", {}):
            return {"error": f"no field {field!r} on type {type_name!r}"}
        v = self._parse_value(value)
        item["fields"].setdefault(field, {"type": "box", "value": None})["value"] = v
        return {"op": "set.instance.field", "instance": instance, "field": field, "value": v}

    def _try_type_patterns(self, t: str) -> Optional[Dict]:
        """Check user-defined device patterns and return a run.instance action if matched."""
        palace = self.current["palace"]
        if palace is None:
            return None
        palace_obj = self.ast["palaces"].get(palace, {})
        for type_name, type_def in palace_obj.get("types", {}).items():
            for dev_name, dev in type_def.get("devices", {}).items():
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
                    if item is not None and item.get("type") == type_name:
                        return {
                            "op": "run.instance",
                            "palace": palace,
                            "room_name": self.current["room"] or "lobby",
                            "instance": instance_name,
                            "device": dev_name,
                            "input": None,
                        }
        return None
