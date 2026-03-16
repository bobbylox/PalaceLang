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
        types = palace_obj.get("types", {})
        # Walk the inheritance chain to find the device
        device = None
        visited = set()
        t = type_name
        while t and t in types and t not in visited:
            visited.add(t)
            candidate = types[t].get(device_name)
            if candidate and isinstance(candidate, dict) and candidate.get("type") == "device":
                device = candidate
                break
            t = types[t].get("parent")
        if not device:
            raise RuntimeError(f"no device {device_name!r} on type {type_name!r}")
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
    # Top-level command execution (single evaluation point)
    # ------------------------------------------------------------------

    def execute(self, command: dict) -> str:
        """Execute a command object returned by IDE.process() and return a display string."""
        op = command.get("operator", "")

        if op == "run":
            palace = command.get("palace")
            room   = command.get("room") or "lobby"
            device = command["device"]
            value  = command.get("input")
            if palace is None:
                return "not inside a palace"
            palace_obj = self.ast.get("palaces", {}).get(palace, {})
            r = palace_obj.get("rooms", {}).get(room)
            if r is None:
                for wing_obj in palace_obj.get("wings", {}).values():
                    r = wing_obj.get("rooms", {}).get(room)
                    if r is not None:
                        break
            r = r or {}
            contents = r.get("contents", {})
            if device not in contents or contents[device].get("type") != "device":
                return f"no device {device}"
            dev_meta = contents[device]
            input_value_type = dev_meta.get("input", {}).get("value_type")
            if value is None and input_value_type is not None:
                return f"{device} requires an input of type {input_value_type}"
            try:
                return str(self.run_device(palace, room, device, value))
            except Exception as e:
                return f"error — {e}"

        if op == "run.instance":
            palace    = command.get("palace")
            room_name = command.get("room_name", "lobby")
            instance  = command["instance"]
            device    = command["device"]
            input_val = command.get("input")
            if palace is None:
                return "not inside a palace"
            try:
                return str(self.run_instance_device(palace, room_name, instance, device, input_val))
            except Exception as e:
                return f"error — {e}"

        if op == "whereami":
            path = command.get("path", [])
            if not path:
                return "outside"
            parts = []
            for frame in reversed(path):
                kind = frame["kind"]
                name = frame["name"]
                if kind == "type_def":
                    parts.append(f"type {name!r}")
                elif kind == "process_chain":
                    parts.append(f"chain {name!r}")
                elif kind == "pattern_chain":
                    parts.append("pattern chain")
                elif kind == "instance":
                    inst_type = frame.get("type", "instance")
                    parts.append(f"{inst_type} {name!r}")
                else:
                    parts.append(f"{kind} {name!r}")
            return "You are in " + " in ".join(parts)

        if op == "query.length":      return str(command["length"])
        if op == "query.step_length": return str(command["length"])
        if op == "query.link":
            return str(command["value"]) if command.get("value_of") else command["description"]
        if op == "look.around":  return command["description"]
        if op == "set.comment":  return "noted"
        if op == "expr.result":  return str(command["value"])
        return "yes"

    # ------------------------------------------------------------------
    # Step execution
    # ------------------------------------------------------------------

    @staticmethod
    def _step_op_args(step) -> tuple:
        """Normalise a step (command object or legacy string) → (operator, args)."""
        if isinstance(step, dict) and step.get("type") == "command":
            return step.get("operator", ""), step.get("arguments", [])
        # Legacy raw-string fallback
        s = step.strip() if isinstance(step, str) else ""
        if not s:
            return "", []
        if s == "else":
            return "else", []
        if s.startswith("return "):
            return "return", [s[7:].strip()]
        if s.startswith("if "):
            return "if", [s[3:].strip()]
        m = (re.match(r"^set new box (\w+) to (.+)$", s) or
             re.match(r"^set new box of (\w+) to (.+)$", s) or
             re.match(r"^set box (\w+) to (.+)$", s))
        if m:
            return "set box", [m.group(1), m.group(2).strip()]
        m = re.match(r"^(\w+) link (.+) is (.+)$", s)
        if m:
            return "link assign", [m.group(1), m.group(2).strip(), m.group(3).strip()]
        return s, []

    def _execute_process(self, steps: List, palace: str, room_name: str,
                         ctx: Dict[str, Any]):
        local: Dict[str, Any] = {}
        i = 0
        while i < len(steps):
            step = steps[i]
            if step is None:
                i += 1
                continue
            op, args = self._step_op_args(step)
            if not op:
                i += 1
                continue

            # --- if CONDITION ---
            if op == "if":
                cond = self._eval_expr(args[0], palace, room_name, ctx, local)
                if cond:
                    i += 1          # execute true branch (next step)
                else:
                    # skip forward to "else" or end
                    i += 1
                    while i < len(steps):
                        s_op, _ = self._step_op_args(steps[i])
                        if s_op == "else":
                            break
                        i += 1
                    i += 1          # step past the "else" marker itself
                continue

            # --- else marker (reached when true-branch didn't return) ---
            if op == "else":
                break

            # --- return EXPR ---
            if op == "return":
                return self._eval_expr(args[0], palace, room_name, ctx, local)

            # --- set box ---
            if op == "set box":
                box_name, expr = args[0], args[1]
                val = self._eval_expr(expr, palace, room_name, ctx, local)
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

            # --- CHAIN link assign ---
            if op == "link assign":
                chain_name, idx_expr, val_expr = args[0], args[1], args[2]
                idx = self._eval_expr(idx_expr, palace, room_name, ctx, local)
                val = self._eval_expr(val_expr, palace, room_name, ctx, local)
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

    def _eval_expr(self, expr, palace: str, room_name: str,
                   ctx: Dict[str, Any], local: Dict[str, Any]):
        # --- typed literal / reference objects (from pre-parser) ---
        if isinstance(expr, dict):
            t = expr.get("type")

            if t in ("integer", "number"):
                return expr["value"]
            if t == "boolean":
                return expr["value"]
            if t == "reference":
                name = expr["name"]
                val = self._eval_expr(name, palace, room_name, ctx, local)
                # Fall back to the name itself so chain names resolve correctly
                # when there is no variable by that name (e.g. "length of sequence")
                return val if val is not None else name

            # command object
            if t == "command":
                op   = expr.get("operator", "")
                args = expr.get("arguments", [])

                def ev(a):
                    return self._eval_expr(a, palace, room_name, ctx, local)

                if op == "less than":
                    lv, rv = ev(args[0]), ev(args[1])
                    return lv < rv if lv is not None and rv is not None else None
                if op == "greater than":
                    lv, rv = ev(args[0]), ev(args[1])
                    return lv > rv if lv is not None and rv is not None else None
                if op == "equal to":
                    lv, rv = ev(args[0]), ev(args[1])
                    return lv == rv if lv is not None and rv is not None else None
                if op == "plus":
                    lv, rv = ev(args[0]), ev(args[1])
                    return lv + rv if lv is not None and rv is not None else None
                if op == "minus":
                    lv, rv = ev(args[0]), ev(args[1])
                    return lv - rv if lv is not None and rv is not None else None
                if op == "multiply":
                    lv, rv = ev(args[0]), ev(args[1])
                    return lv * rv if lv is not None and rv is not None else None
                if op == "divide":
                    lv, rv = ev(args[0]), ev(args[1])
                    return lv / rv if lv is not None and rv is not None and rv != 0 else None
                if op == "squared":
                    v = ev(args[0])
                    return v ** 2 if v is not None else None
                if op == "cubed":
                    v = ev(args[0])
                    return v ** 3 if v is not None else None
                if op == "length of":
                    chain_name = ev(args[0])
                    room = self._find_room(palace, room_name)
                    ch = room["contents"].get(chain_name)
                    return len(ch["links"]) if ch and ch.get("type") == "chain" else 0
                if op == "chain link":
                    chain_name = ev(args[0])
                    idx = ev(args[1])
                    if idx is None:
                        return None
                    idx = int(idx)
                    room = self._find_room(palace, room_name)
                    ch = room["contents"].get(chain_name)
                    links = ch["links"] if ch and ch.get("type") == "chain" else []
                    i0 = idx - 1
                    if i0 < 0:
                        return None
                    if i0 >= len(links) or links[i0].get("value") is None:
                        dev = ctx.get("device_name")
                        if dev:
                            return self.run_device(palace, room_name, dev, idx)
                        return None
                    return links[i0]["value"]
                if op == "chain get":
                    chain_name = ev(args[0])
                    idx = ev(args[1])
                    if isinstance(idx, int):
                        room = self._find_room(palace, room_name)
                        ch = room["contents"].get(chain_name)
                        links = ch["links"] if ch and ch.get("type") == "chain" else []
                        i0 = idx - 1
                        if 0 <= i0 < len(links):
                            return links[i0].get("value")
                return None

            return None  # unknown dict type

        # --- legacy string expression (variable lookup + raw arithmetic fallback) ---
        if not isinstance(expr, str):
            return None
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
        if instance_obj is not None and s != "type" and s in instance_obj:
            return instance_obj[s].get("value")

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

        # CHAIN link EXPR
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
            i0 = idx - 1
            if i0 < 0:
                return None
            if i0 >= len(links) or links[i0].get("value") is None:
                dev = ctx.get("device_name")
                if dev:
                    return self.run_device(palace, room_name, dev, idx)
                return None
            return links[i0]["value"]

        # CHAIN EXPR shorthand
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

        # comparison operators
        for op_str, op_fn in [
            ("is less than",    lambda a, b: a < b),
            ("is greater than", lambda a, b: a > b),
            ("is equal to",     lambda a, b: a == b),
        ]:
            pat = f" {op_str} "
            if pat in s:
                left, right = s.split(pat, 1)
                lv = self._eval_expr(left, palace, room_name, ctx, local)
                rv = self._eval_expr(right, palace, room_name, ctx, local)
                if lv is not None and rv is not None:
                    return op_fn(lv, rv)

        if " plus " in s:
            parts = s.split(" plus ")
            vals = [self._eval_expr(p, palace, room_name, ctx, local) for p in parts]
            if all(v is not None for v in vals):
                return sum(vals)

        if " minus " in s:
            a, b = s.rsplit(" minus ", 1)
            av = self._eval_expr(a, palace, room_name, ctx, local)
            bv = self._eval_expr(b, palace, room_name, ctx, local)
            if av is not None and bv is not None:
                return av - bv

        if " times " in s:
            parts = s.split(" times ")
            result = None
            for p in parts:
                v = self._eval_expr(p, palace, room_name, ctx, local)
                if v is None:
                    return None
                result = v if result is None else result * v
            return result

        if " divided by " in s:
            a, b = s.split(" divided by ", 1)
            av = self._eval_expr(a, palace, room_name, ctx, local)
            bv = self._eval_expr(b, palace, room_name, ctx, local)
            if av is not None and bv is not None and bv != 0:
                return av / bv

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
