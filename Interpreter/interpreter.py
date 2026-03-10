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
    # Public entry point
    # ------------------------------------------------------------------

    def run_device(self, palace: str, room_name: str, device: str,
                   input_value=None):
        p = self.ast.get("palaces", {}).get(palace)
        if not p:
            raise RuntimeError(f"no palace {palace}")
        r = p.get("rooms", {}).get(room_name)
        if not r:
            raise RuntimeError(f"no room {room_name} in palace {palace}")
        d = r.get("devices", {}).get(device)
        if not d:
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

            # --- set new box NAME to EXPR ---
            m = re.match(r"^set new box (\w+) to (.+)$", step)
            if m:
                local[m.group(1)] = self._eval_expr(
                    m.group(2), palace, room_name, ctx, local)
                i += 1
                continue

            # --- CHAIN link EXPR is EXPR  (chain-link assignment) ---
            m = re.match(r"^(\w+) link (.+) is (.+)$", step)
            if m:
                chain_name = m.group(1)
                idx = self._eval_expr(m.group(2), palace, room_name, ctx, local)
                val = self._eval_expr(m.group(3), palace, room_name, ctx, local)
                if idx is not None and val is not None:
                    room = self.ast["palaces"][palace]["rooms"][room_name]
                    ch = room["chains"].setdefault(chain_name, {"links": []})
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

        # literal boolean
        if s.lower() == "true":
            return True
        if s.lower() == "false":
            return False

        # local variable (check before input so named boxes win)
        if s in local:
            return local[s]

        # input variable (by canonical name "input" or custom name e.g. "place")
        if s == "input" or s == ctx.get("input_name"):
            return ctx.get("input")

        # length of CHAIN
        m = re.match(r"^length of (\w+)$", s)
        if m:
            room = self.ast["palaces"][palace]["rooms"][room_name]
            ch = room["chains"].get(m.group(1), {"links": []})
            return len(ch["links"])

        # CHAIN link EXPR  — e.g. "sequence link input minus 2"
        # The EXPR after "link" becomes the 1-based index
        m = re.match(r"^(\w+) link (.+)$", s)
        if m:
            chain_name = m.group(1)
            idx = self._eval_expr(m.group(2), palace, room_name, ctx, local)
            if idx is None:
                return None
            idx = int(idx)
            room = self.ast["palaces"][palace]["rooms"][room_name]
            ch = room["chains"].get(chain_name, {"links": []})
            links = ch["links"]
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
                room = self.ast["palaces"][palace]["rooms"][room_name]
                ch = room["chains"].get(chain_name, {"links": []})
                links = ch["links"]
                i0 = idx - 1
                if 0 <= i0 < len(links):
                    return links[i0].get("value")

        # comparison operators (must come before arithmetic)
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

        # subtraction (split on last " minus " to handle e.g. "input minus 2")
        if " minus " in s:
            a, b = s.split(" minus ", 1)
            av = self._eval_expr(a, palace, room_name, ctx, local)
            bv = self._eval_expr(b, palace, room_name, ctx, local)
            if av is not None and bv is not None:
                return av - bv

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
