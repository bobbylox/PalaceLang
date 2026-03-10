import re
import json
from typing import Any, Dict, List, Optional, Tuple


class IDE:
    """Voice-command -> AST translator for Palace Language.

    Keeps a workspace in-memory and can dump it as JSON.
    Covers all commands in the canonical example session.
    """

    def __init__(self):
        self.ast: Dict[str, Any] = {"palaces": {}}
        self.current = {
            "palace": None, "room": None, "device": None, "in_process": False
        }
        self._last_name: Optional[str] = None      # for "it" pronoun
        self._last_link_chain: Optional[str] = None  # for "set link value"

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
        return self.ast["palaces"].setdefault(name, {"rooms": {}})

    def _ensure_room(self, palace: str, room: str) -> Dict:
        p = self._ensure_palace(palace)
        return p["rooms"].setdefault(room, {"chains": {}, "devices": {}})

    def _current_room_obj(self) -> Optional[Dict]:
        p = self.current["palace"]
        if p is None:
            return None
        r = self.current["room"] or "lobby"
        return self._ensure_room(p, r)

    def _current_device_obj(self) -> Optional[Dict]:
        room = self._current_room_obj()
        if room is None:
            return None
        dev = self.current["device"]
        if dev is None:
            return None
        return room["devices"].get(dev)

    # ------------------------------------------------------------------
    # Pre-processing
    # ------------------------------------------------------------------

    def _preprocess(self, utterance: str) -> str:
        t = utterance.strip()
        # strip optional line-end markers
        if t.endswith(" over"):
            t = t[:-5].strip()
        if t.endswith(" stop"):
            t = t[:-5].strip()
        # resolve "it" pronoun
        if self._last_name:
            t = re.sub(r'\bit\b', self._last_name, t, flags=re.IGNORECASE)
        return t

    # ------------------------------------------------------------------
    # Main dispatcher
    # ------------------------------------------------------------------

    def process(self, utterance: str) -> Dict[str, Any]:
        t = self._preprocess(utterance)

        patterns: List[Tuple[str, Any]] = [
            # --- Queries (most specific first) ---
            (r"^where am [Ii]\?*$", self._cmd_whereami),
            (r"^what is (?:the )?step length\??$", self._cmd_step_length),
            (r"^what is (?:the )?(?P<value_of>value of )?(?P<chain>\w+)(?:'s)? link (?P<idx>\d+)\??$",
             self._cmd_query_link),
            (r"^(?:what is (?:the )?)?length of (?P<chain>\w+)\??$",
             self._cmd_length),

            # --- Palace & navigation ---
            (r"^palace (?:called |named )?(?P<name>\w+)$", self._cmd_palace),
            (r"^enter (?:new )?device (?P<name>\w+)$", self._cmd_device),
            (r"^enter process$", self._cmd_enter_process),
            (r"^enter (?P<name>\w+)$", self._cmd_enter),
            (r"^go to (?P<room>\w+)$", self._cmd_go_to),
            (r"^go outside$", self._cmd_go_outside),
            (r"^exit$", self._cmd_exit),

            # --- Creation ---
            (r"^room (?P<name>\w+)$", self._cmd_room),
            (r"^chain (?P<name>\w+)$", self._cmd_chain),

            # --- Append ---
            (r"^append link to (?P<chain>\w+)$", self._cmd_append_link),
            (r"^append (?P<value>.+) to (?P<chain>\w+)$",
             self._cmd_append_to_chain),

            # --- Set (specific → general) ---
            (r"^set link value (?:to )?(?P<value>.+)$",
             self._cmd_set_link_value),
            (r"^set (?P<chain>\w+)(?:'s)? link (?P<idx>\d+) to (?P<value>.+)$",
             self._cmd_set_chain_link),
            (r"^set input name to (?P<value>.+)$", self._cmd_set_input_name),
            (r"^set input type to (?P<value>.+)$", self._cmd_set_input_type),
            (r"^set comment to (?P<value>.+)$", self._cmd_set_comment),
            (r"^set step (?P<idx>\d+) to (?P<body>.+)$", self._cmd_set_step),

            # --- Then (step-append sugar) ---
            (r"^then (?P<body>.+)$", self._cmd_then),

            # --- Run (3-level → 2-level → 1-level) ---
            (r"^run (?P<palace>\w+)'s (?P<room>\w+)'s (?P<device>\w+)"
             r"(?: on (?P<value>.+))?$", self._cmd_run_full),
            (r"^run (?P<room>\w+)'s (?P<device>\w+)(?: on (?P<value>.+))?$",
             self._cmd_run_room),
            (r"^run (?P<device>\w+)(?: on (?P<value>.+))?$", self._cmd_run),
        ]

        for pat, fn in patterns:
            m = re.match(pat, t, re.IGNORECASE)
            if m:
                res = fn(**m.groupdict())
                if isinstance(res, dict):
                    if "name" in res:
                        self._last_name = res["name"]
                    if "error" in res:
                        return {"ok": False, "error": res["error"]}
                return {"ok": True, "action": res}

        return {"ok": False, "error": f"unrecognized: {t}"}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _parse_value(self, s: str) -> Any:
        s = s.strip()
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
            "palace": name, "room": None,
            "device": None, "in_process": False
        }
        return {"op": "palace.create", "name": name}

    def _cmd_enter(self, name: str) -> Dict:
        # enter a palace?
        if name in self.ast["palaces"]:
            self.current = {
                "palace": name, "room": None,
                "device": None, "in_process": False
            }
            return {"op": "enter.palace", "name": name}

        palace = self.current["palace"]
        if palace is None:
            return {"error": "no palace"}

        rooms = self.ast["palaces"][palace]["rooms"]

        # enter an existing room?
        if name in rooms:
            self.current.update({"room": name, "device": None,
                                 "in_process": False})
            return {"op": "enter.room", "name": name}

        # enter an existing device in the current room?
        room_name = self.current["room"] or "lobby"
        r = self._ensure_room(palace, room_name)
        if name in r["devices"]:
            self.current.update({"device": name, "in_process": False})
            return {"op": "enter.device", "name": name}

        # implicitly create a new room
        self._ensure_room(palace, name)
        self.current.update({"room": name, "device": None,
                             "in_process": False})
        return {"op": "enter.room.create", "name": name}

    def _cmd_go_to(self, room: str) -> Dict:
        palace = self.current["palace"]
        if palace is None:
            return {"error": "no palace"}
        rooms = self.ast["palaces"][palace]["rooms"]
        if room not in rooms:
            return {"error": f"no room {room}"}
        self.current.update({"room": room, "device": None,
                             "in_process": False})
        return {"op": "go.room", "name": room}

    def _cmd_go_outside(self) -> Dict:
        self.current = {
            "palace": None, "room": None,
            "device": None, "in_process": False
        }
        return {"op": "go.outside"}

    def _cmd_exit(self) -> Dict:
        if self.current["in_process"]:
            self.current["in_process"] = False
            return {"op": "exit.process"}
        if self.current["device"] is not None:
            self.current["device"] = None
            return {"op": "exit.device"}
        if self.current["room"] is not None:
            self.current["room"] = None
            return {"op": "exit.room"}
        if self.current["palace"] is not None:
            self.current["palace"] = None
            return {"op": "exit.palace"}
        return {"op": "exit"}

    def _cmd_room(self, name: str) -> Dict:
        palace = self.current["palace"]
        if palace is None:
            return {"error": "no palace"}
        self._ensure_room(palace, name)
        return {"op": "room.create", "name": name}

    def _cmd_chain(self, name: str) -> Dict:
        palace = self.current["palace"]
        room = self.current["room"]
        if palace is None:
            return {"error": "no palace"}
        if room is None:
            return {"error": "chain must be in a room"}
        r = self._ensure_room(palace, room)
        r["chains"].setdefault(name, {"links": []})
        self._last_link_chain = name
        return {"op": "chain.create", "name": name}

    def _cmd_append_link(self, chain: str) -> Dict:
        palace = self.current["palace"]
        room = self.current["room"] or "lobby"
        if palace is None:
            return {"error": "no palace"}
        r = self._ensure_room(palace, room)
        ch = r["chains"].setdefault(chain, {"links": []})
        ch["links"].append({"value": None})
        self._last_link_chain = chain
        return {"op": "chain.append_link", "chain": chain}

    def _cmd_append_to_chain(self, value: str, chain: str) -> Dict:
        palace = self.current["palace"]
        room = self.current["room"] or "lobby"
        if palace is None:
            return {"error": "no palace"}
        r = self._ensure_room(palace, room)
        ch = r["chains"].setdefault(chain, {"links": []})
        v = self._parse_value(value)
        # type check
        chain_type = self._chain_type(ch)
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
        room = self.current["room"] or "lobby"
        if palace is None:
            return {"error": "no palace"}
        chain = self._last_link_chain
        if chain is None:
            return {"error": "no recent chain link to set"}
        r = self._ensure_room(palace, room)
        ch = r["chains"].get(chain)
        if not ch or not ch["links"]:
            return {"error": f"no links in {chain}"}
        v = self._parse_value(value)
        ch["links"][-1]["value"] = v
        return {"op": "set.link.value", "chain": chain, "value": v}

    def _cmd_set_chain_link(self, chain: str, idx: str, value: str) -> Dict:
        palace = self.current["palace"]
        room = self.current["room"] or "lobby"
        if palace is None:
            return {"error": "no palace"}
        r = self._ensure_room(palace, room)
        ch = r["chains"].setdefault(chain, {"links": []})
        i = int(idx) - 1      # 1-based → 0-based
        v = self._parse_value(value)
        while len(ch["links"]) <= i:
            ch["links"].append({"value": None})
        ch["links"][i]["value"] = v
        return {"op": "set.chain.link", "chain": chain, "index": i, "value": v}

    def _cmd_set_input_name(self, value: str) -> Dict:
        d = self._current_device_obj()
        if d is None:
            return {"error": "not in a device"}
        d.setdefault("input", {})["name"] = value
        return {"op": "set.input.name", "value": value}

    def _cmd_set_input_type(self, value: str) -> Dict:
        d = self._current_device_obj()
        if d is None:
            return {"error": "not in a device"}
        d.setdefault("input", {})["type"] = value
        return {"op": "set.input.type", "value": value}

    def _cmd_set_comment(self, value: str) -> Dict:
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
        steps = d.setdefault("process", [])
        i = int(idx) - 1
        while len(steps) <= i:
            steps.append("")
        steps[i] = body
        return {"op": "device.set.step", "step": int(idx), "body": body}

    def _cmd_then(self, body: str) -> Dict:
        d = self._current_device_obj()
        if d is None:
            return {"error": "not in a device"}
        steps = d.setdefault("process", [])
        steps.append(body)
        return {"op": "device.append.step", "body": body}

    def _cmd_device(self, name: str) -> Dict:
        palace = self.current["palace"]
        room = self.current["room"] or "lobby"
        if palace is None:
            return {"error": "no palace"}
        r = self._ensure_room(palace, room)
        r["devices"].setdefault(name, {
            "input": {"name": "input", "type": "untyped"},
            "process": [],
            "comment": "",
        })
        self.current["device"] = name
        self.current["in_process"] = False
        return {"op": "device.create", "name": name}

    def _cmd_enter_process(self) -> Dict:
        if self._current_device_obj() is None:
            return {"error": "not in a device"}
        self.current["in_process"] = True
        return {"op": "enter.process"}

    # --- query handlers ---

    def _cmd_whereami(self) -> Dict:
        return {
            "op": "whereami",
            "palace": self.current["palace"],
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
        room = self.current["room"] or "lobby"
        if palace is None:
            return {"error": "no palace"}
        r = self._ensure_room(palace, room)
        ch = r["chains"].get(chain)
        if ch is None:
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
        room = self.current["room"] or "lobby"
        if palace is None:
            return {"error": "no palace"}
        r = self._ensure_room(palace, room)
        ch = r["chains"].get(chain, {"links": []})
        return {"op": "query.length", "chain": chain,
                "length": len(ch["links"])}

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
        return {
            "op": "run",
            "palace": self.current["palace"],
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
