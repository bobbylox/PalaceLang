import re
import json
from typing import Any, Dict, List, Optional


class Interpreter:
    """Executes devices from a Palace Language AST.

    Steps are stored as plain strings; the interpreter pattern-matches them at
    runtime.  Sequence lookups auto-recurse so memoised fibonacci works.
    """

    def __init__(self, ast: Dict[str, Any]):
        self.ast = ast

    @classmethod
    def load_from_file(cls, path: str):
        with open(path) as f:
            return cls(json.load(f))

    # ------------------------------------------------------------------
    # AST helpers
    # ------------------------------------------------------------------

    def _palace_type_name(self, v: Any) -> str:
        if isinstance(v, bool):
            return "boolean"
        if isinstance(v, (int, float)):
            return "number"
        if isinstance(v, str):
            return "string"
        return "unknown"

    def _value_matches_type(self, v: Any, btype: str) -> bool:
        if btype == "boolean":
            return isinstance(v, bool)
        if btype == "number":
            return isinstance(v, (int, float)) and not isinstance(v, bool)
        if btype == "string":
            return isinstance(v, str)
        return True  # unknown type — permissive

    def _find_room(self, palace: str, room_name: str) -> Optional[Dict]:
        """Locate a room by name, searching palace-level rooms then all wings."""
        p = self.ast.get("palaces", {}).get(palace)
        if not p:
            return None
        if room_name in p.get("rooms", {}):
            return p["rooms"][room_name]
        for wing in p.get("wings", {}).values():
            if room_name in wing.get("rooms", {}):
                return wing["rooms"][room_name]
        return None

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run_device(self, palace: str, room_name: str, device: str,
                   input_value=None):
        p = self.ast.get("palaces", {}).get(palace)
        if not p:
            raise RuntimeError(f"no palace {palace}")
        r = self._find_room(palace, room_name)
        if not r:
            raise RuntimeError(f"no room {room_name} in palace {palace}")
        d = r.get("contents", {}).get(device)
        if not d or d.get("type") != "device":
            raise RuntimeError(f"no device {device} in {palace}/{room_name}")

        input_name = d.get("input", {}).get("name", "input")
        ctx = {
            "input": input_value,
            "input_name": input_name,
            "device_name": device,
            "palace": palace,
            "room": room_name,
        }
        return self._execute_process(d.get("process", []), palace, room_name, ctx)

    def run_instance_device(self, palace: str, room_name: str, instance_name: str,
                            device_name: str, input_value=None):
        """Execute a user-type method device in the context of a named instance."""
        r = self._find_room(palace, room_name)
        if not r:
            raise RuntimeError(f"no room {room_name}")
        instance = r.get("contents", {}).get(instance_name)
        if not instance:
            raise RuntimeError(f"no instance {instance_name!r}")
        type_name = instance.get("type")
        palace_obj = self.ast.get("palaces", {}).get(palace, {})
        type_def = palace_obj.get("types", {}).get(type_name)
        if not type_def:
            raise RuntimeError(f"no type {type_name!r}")
        device = type_def.get("devices", {}).get(device_name)
        if not device:
            raise RuntimeError(f"no method {device_name!r} on type {type_name!r}")
        input_name = device.get("input", {}).get("name", "input")
        ctx = {
            "input": input_value,
            "input_name": input_name,
            "device_name": device_name,
            "palace": palace,
            "room": room_name,
            "instance": instance,
        }
        return self._execute_process(device.get("process", []), palace, room_name, ctx)

    # ------------------------------------------------------------------
    # Step execution
    # ------------------------------------------------------------------

    def _execute_process(self, steps: List[str], palace: str, room_name: str,
                         ctx: Dict[str, Any]):
        local: Dict[str, Any] = {}
        i = 0
        while i < len(steps):
            step = steps[i].strip()
            if not step:
                i += 1
                continue

            # --- if CONDITION ---
            if step.startswith("if "):
                cond = self._eval_expr(step[3:], palace, room_name, ctx, local)
                if cond:
                    i += 1          # execute true branch (next step)
                else:
                    # skip forward to "else" or end
                    i += 1
                    while i < len(steps) and steps[i].strip() != "else":
                        i += 1
                    i += 1          # step past the "else" marker itself
                continue

            # --- else marker (reached when true-branch didn't return) ---
            if step == "else":
                break

            # --- return EXPR ---
            if step.startswith("return "):
                return self._eval_expr(step[7:], palace, room_name, ctx, local)

            # --- set box / set new box (NAME | of TYPE) to EXPR ---
            m = (re.match(r"^set new box (\w+) to (.+)$", step) or
                 re.match(r"^set new box of (\w+) to (.+)$", step) or
                 re.match(r"^set box (\w+) to (.+)$", step))
            if m:
                box_name = m.group(1)
                val = self._eval_expr(m.group(2), palace, room_name, ctx, local)
                room_obj = self._find_room(palace, room_name)
                dev_obj = room_obj.get("contents", {}).get(ctx.get("device_name"), {})
                dev_boxes = dev_obj.get("boxes", {})
                room_contents = room_obj.get("contents", {})
                if box_name in dev_boxes:
                    entry = dev_boxes[box_name]
                    btype = entry.get("value_type")
                    if btype and not self._value_matches_type(val, btype):
                        vtype = self._palace_type_name(val)
                        raise RuntimeError(
                            f"cannot set box of type {btype} to {vtype} value")
                    entry["value"] = val
                elif box_name in room_contents and room_contents[box_name].get("type") == "box":
                    entry = room_contents[box_name]
                    btype = entry.get("value_type")
                    if btype and not self._value_matches_type(val, btype):
                        vtype = self._palace_type_name(val)
                        raise RuntimeError(
                            f"cannot set box of type {btype} to {vtype} value")
                    entry["value"] = val
                else:
                    local[box_name] = val
                i += 1
                continue

            # --- CHAIN link EXPR is EXPR  (chain-link assignment) ---
            m = re.match(r"^(\w+) link (.+) is (.+)$", step)
            if m:
                chain_name = m.group(1)
                idx = self._eval_expr(m.group(2), palace, room_name, ctx, local)
                val = self._eval_expr(m.group(3), palace, room_name, ctx, local)
                if idx is not None and val is not None:
                    room = self._find_room(palace, room_name)
                    ch = room["contents"].setdefault(chain_name, {"type": "chain", "links": []})
                    links = ch["links"]
                    i0 = int(idx) - 1          # 1-based → 0-based
                    while len(links) <= i0:
                        links.append({"value": None})
                    links[i0]["value"] = val
                i += 1
                continue

            i += 1
        return None

    # ------------------------------------------------------------------
    # Expression evaluation
    # ------------------------------------------------------------------

    def _eval_expr(self, expr: str, palace: str, room_name: str,
                   ctx: Dict[str, Any], local: Dict[str, Any]):
        s = expr.strip()

        # literal integer
        try:
            return int(s)
        except ValueError:
            pass

        # literal float
        try:
            return float(s)
        except ValueError:
            pass

        # literal boolean
        if s.lower() == "true":
            return True
        if s.lower() == "false":
            return False

        # local variable (highest priority)
        if s in local:
            return local[s]

        # instance field (when executing in user-type method context)
        instance_obj = ctx.get("instance")
        if instance_obj is not None and s in instance_obj.get("fields", {}):
            return instance_obj["fields"][s].get("value")

        # device-level box
        room_obj = self._find_room(palace, room_name)
        dev_obj = room_obj.get("contents", {}).get(ctx.get("device_name"), {})
        dev_boxes = dev_obj.get("boxes", {})
        if s in dev_boxes:
            return dev_boxes[s].get("value")

        # room-level box
        room_contents = room_obj.get("contents", {})
        if s in room_contents and room_contents[s].get("type") == "box":
            return room_contents[s]["value"]

        # input variable (by canonical name "input" or custom name e.g. "place")
        if s == "input" or s == ctx.get("input_name"):
            return ctx.get("input")

        # length of CHAIN
        m = re.match(r"^length of (\w+)$", s)
        if m:
            room = self._find_room(palace, room_name)
            ch = room["contents"].get(m.group(1))
            return len(ch["links"]) if ch and ch.get("type") == "chain" else 0

        # CHAIN link EXPR  — e.g. "sequence link input minus 2"
        # The EXPR after "link" becomes the 1-based index
        m = re.match(r"^(\w+) link (.+)$", s)
        if m:
            chain_name = m.group(1)
            idx = self._eval_expr(m.group(2), palace, room_name, ctx, local)
            if idx is None:
                return None
            idx = int(idx)
            room = self._find_room(palace, room_name)
            ch = room["contents"].get(chain_name)
            links = ch["links"] if ch and ch.get("type") == "chain" else []
            i0 = idx - 1                        # 1-based → 0-based
            if i0 < 0:
                return None
            # auto-recurse to fill missing / None slots (memoised fibonacci)
            if i0 >= len(links) or links[i0].get("value") is None:
                dev = ctx.get("device_name")
                if dev:
                    val = self.run_device(palace, room_name, dev, idx)
                    return val
                return None
            return links[i0]["value"]

        # CHAIN EXPR  — shorthand e.g. "sequence input" (no "link" keyword)
        m = re.match(r"^(\w+) (\w.*)$", s)
        if m:
            chain_name = m.group(1)
            idx = self._eval_expr(m.group(2), palace, room_name, ctx, local)
            if isinstance(idx, int):
                room = self._find_room(palace, room_name)
                ch = room["contents"].get(chain_name)
                links = ch["links"] if ch and ch.get("type") == "chain" else []
                i0 = idx - 1
                if 0 <= i0 < len(links):
                    return links[i0].get("value")

        # comparison operators (lowest precedence)
        for op_str, op_fn in [
            ("is less than", lambda a, b: a < b),
            ("is greater than", lambda a, b: a > b),
            ("is equal to", lambda a, b: a == b),
        ]:
            pat = f" {op_str} "
            if pat in s:
                left, right = s.split(pat, 1)
                lv = self._eval_expr(left, palace, room_name, ctx, local)
                rv = self._eval_expr(right, palace, room_name, ctx, local)
                if lv is not None and rv is not None:
                    return op_fn(lv, rv)

        # addition
        if " plus " in s:
            parts = s.split(" plus ")
            vals = [self._eval_expr(p, palace, room_name, ctx, local)
                    for p in parts]
            if all(v is not None for v in vals):
                return sum(vals)

        # subtraction — rsplit for left-associativity: a-b-c = (a-b)-c
        if " minus " in s:
            a, b = s.rsplit(" minus ", 1)
            av = self._eval_expr(a, palace, room_name, ctx, local)
            bv = self._eval_expr(b, palace, room_name, ctx, local)
            if av is not None and bv is not None:
                return av - bv

        # multiplication
        if " times " in s:
            parts = s.split(" times ")
            result = None
            for p in parts:
                v = self._eval_expr(p, palace, room_name, ctx, local)
                if v is None:
                    return None
                result = v if result is None else result * v
            return result

        # division
        if " divided by " in s:
            a, b = s.split(" divided by ", 1)
            av = self._eval_expr(a, palace, room_name, ctx, local)
            bv = self._eval_expr(b, palace, room_name, ctx, local)
            if av is not None and bv is not None and bv != 0:
                return av / bv

        # postfix powers (highest arithmetic precedence)
        if s.endswith(" squared"):
            v = self._eval_expr(s[:-8], palace, room_name, ctx, local)
            return v ** 2 if v is not None else None
        if s.endswith(" cubed"):
            v = self._eval_expr(s[:-6], palace, room_name, ctx, local)
            return v ** 3 if v is not None else None

        return None


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 5:
        print("Usage: interpreter.py <ast.json> <palace> <room> <device> [input]")
        raise SystemExit(2)
    astfile, palace, room, device = sys.argv[1:5]
    inp = int(sys.argv[5]) if len(sys.argv) > 5 else None
    interp = Interpreter.load_from_file(astfile)
    print(interp.run_device(palace, room, device, inp))
