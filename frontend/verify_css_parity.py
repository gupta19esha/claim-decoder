"""
Prove the stylesheet refactor changed nothing visible.

Reads the pre-refactor styles.css out of git, reads the new @import tree,
resolves every custom property to a literal, expands the shorthands that the
refactor split across rules (a `border` in card.css overridden by a
`border-color` in field.css must compare equal to the single `border` it
replaced), then merges all declarations that apply to each selector in source
order and diffs the result.

Not a browser. It compares per-selector declaration sets, which is exactly
the property the refactor must preserve: the same element, matched by the
same selector, ends up with the same computed values.

    python verify_css_parity.py
"""

import re
import subprocess
import sys
from pathlib import Path

OLD_REF = "HEAD:frontend/src/styles.css"
NEW_ENTRY = Path("src/styles/index.css")
NEW_APP = Path("src/App.jsx")

BOX = ("top", "right", "bottom", "left")
CORNERS = ("top-left", "top-right", "bottom-right", "bottom-left")


# ------------------------------------------------------------------ parsing

def strip_comments(css):
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def parse(css):
    """-> list of (context, selector, [(prop, value), ...]) in source order."""
    rules = []

    def walk(text, ctx):
        pos = 0
        while pos < len(text):
            brace = text.find("{", pos)
            if brace == -1:
                break
            semi = text.find(";", pos)
            if semi != -1 and semi < brace:      # @import and friends
                pos = semi + 1
                continue
            sel = text[pos:brace].strip()
            depth, j = 1, brace + 1
            while j < len(text) and depth:
                if text[j] == "{":
                    depth += 1
                elif text[j] == "}":
                    depth -= 1
                j += 1
            body = text[brace + 1:j - 1]
            if sel.startswith("@"):
                walk(body, (ctx + " " + re.sub(r"\s+", " ", sel)).strip())
            else:
                decls = []
                for d in body.split(";"):
                    d = d.strip()
                    if not d or ":" not in d:
                        continue
                    p, v = d.split(":", 1)
                    decls.append((p.strip(), re.sub(r"\s+", " ", v.strip())))
                for one in (s.strip() for s in sel.split(",")):
                    if one:
                        rules.append((ctx, re.sub(r"\s+", " ", one), decls))
            pos = j

    walk(strip_comments(css), "")
    return rules


def inline_imports(entry):
    seen = []

    def load(path):
        text = strip_comments(path.read_text(encoding="utf-8"))
        out = []
        for line in text.splitlines():
            m = re.match(r'\s*@import\s+["\'](.+?)["\']\s*;', line)
            if m:
                out.append(load((path.parent / m.group(1)).resolve()))
            else:
                out.append(line)
        seen.append(path.name)
        return "\n".join(out)

    return load(entry.resolve())


# ------------------------------------------------------------ var resolution

VAR_RE = re.compile(r"var\(\s*(--[\w-]+)\s*(?:,\s*([^()]*))?\)")


def collect_vars(rules):
    out = {}
    for ctx, sel, decls in rules:
        if sel == ":root" and not ctx:
            for p, v in decls:
                if p.startswith("--"):
                    out[p] = v
    return out


def resolve(value, variables, depth=0):
    if depth > 30 or "var(" not in value:
        return value

    def rep(m):
        name, fallback = m.group(1), m.group(2)
        if name in variables:
            return resolve(variables[name], variables, depth + 1)
        return (fallback or "").strip()

    return re.sub(r"\s+", " ", VAR_RE.sub(rep, value)).strip()


# ------------------------------------------------------------- shorthands

def split_values(v):
    return [p for p in re.split(r"\s+(?![^(]*\))", v.strip()) if p]


def expand_box(prop, value):
    parts = split_values(value)
    if len(parts) == 1:
        parts *= 4
    elif len(parts) == 2:
        parts = [parts[0], parts[1], parts[0], parts[1]]
    elif len(parts) == 3:
        parts = [parts[0], parts[1], parts[2], parts[1]]
    return {f"{prop}-{side}": p for side, p in zip(BOX, parts[:4])}


def expand_border_value(value):
    """`1px solid #dcd7cc` -> width/style/colour, in any order."""
    out = {}
    for part in split_values(value):
        if part in ("solid", "dashed", "dotted", "none", "hidden", "double"):
            out["style"] = part
        elif re.match(r"^[\d.]+(px|em|rem)$|^(thin|medium|thick)$", part):
            out["width"] = part
        else:
            out["color"] = part
    return out


def expand(prop, value):
    """Return a dict of longhand -> value."""
    if prop in ("margin", "padding"):
        return expand_box(prop, value)
    if prop == "border-radius":
        parts = split_values(value)
        if len(parts) == 1:
            parts *= 4
        elif len(parts) == 2:
            parts = [parts[0], parts[1], parts[0], parts[1]]
        elif len(parts) == 3:
            parts = [parts[0], parts[1], parts[2], parts[1]]
        return {f"border-{c}-radius": p for c, p in zip(CORNERS, parts[:4])}
    if prop == "border":
        bits = expand_border_value(value)
        return {f"border-{side}-{k}": v
                for side in BOX for k, v in bits.items()}
    if prop in (f"border-{s}" for s in BOX):
        side = prop.split("-", 1)[1]
        return {f"border-{side}-{k}": v
                for k, v in expand_border_value(value).items()}
    if prop == "border-color":
        return expand_box("border", value) and {
            f"border-{side}-color": p
            for side, p in zip(BOX, (split_values(value) * 4)[:4])
        }
    if prop == "border-width":
        return {f"border-{side}-width": p
                for side, p in zip(BOX, (split_values(value) * 4)[:4])}
    if prop == "outline":
        return {f"outline-{k}": v for k, v in expand_border_value(value).items()}
    return {prop: value}


# ------------------------------------------------------------------ compare

def computed(rules, variables):
    """(context, selector) -> {longhand: value}, applied in source order."""
    out = {}
    for ctx, sel, decls in rules:
        if sel == ":root":
            continue
        key = (ctx, sel)
        bucket = out.setdefault(key, {})
        for prop, value in decls:
            if prop.startswith("--"):
                continue
            bucket.update(expand(prop, resolve(value, variables)))
    return out


# ------------------------------------------------------- migration mapping
#
# The markup migration replaced bare element selectors with component
# classes, so a straight per-selector diff would report every one of them as
# removed. These maps say what each old selector became. Values merge in
# order, which must match the @import order in styles/index.css.

ALIASES = {
    "button": [".btn"],
    "button:hover:not(:disabled)": [".btn:hover:not(:disabled)"],
    "button:disabled": [".btn:disabled"],
    "button.ghost": [".btn.ghost"],
    "button.ghost:hover:not(:disabled)": [".btn.ghost:hover:not(:disabled)"],
    "button:focus-visible": [".btn:focus-visible"],
    "input": [".input"],
    "select": [".select"],
    "textarea": [".textarea"],
    "input:disabled": [".input:disabled"],
    "select:disabled": [".select:disabled"],
    "textarea:disabled": [".textarea:disabled"],
    "input:focus": [".input:focus"],
    "select:focus": [".select:focus"],
    "textarea:focus": [".textarea:focus"],
    "label": [".label"],
    "summary:focus-visible": [".extras summary:focus-visible"],
}

# Surfaces that used to restate background/border/radius and now take them
# from .card in the markup.
COMPOSED = {
    ".verdict": [".card", ".verdict"],
    ".exhibit": [".card", ".exhibit"],
    ".arg": [".card", ".arg"],
    ".extras": [".card", ".extras"],
    ".letter": [".card", ".letter"],
    ".notice": [".card", ".notice"],
}

# tag -> class every instance of that tag must now carry.
REQUIRED_CLASS = {
    "button": "btn", "input": "input", "select": "select",
    "textarea": "textarea", "label": "label",
}

# Elements that must carry `card`, recognised by a class they already had.
REQUIRED_CARD = {"verdict", "exhibit", "arg", "extras", "letter", "notice"}


def jsx_elements(src):
    """(tag, [classes]) for every element, in source order.

    Attribute values contain arrow functions, so an opening tag cannot be
    found by scanning to the next '>'. Track brace depth instead.
    """
    out = []
    for m in re.finditer(r"<([a-z][a-zA-Z0-9]*)\b", src):
        i, depth = m.end(), 0
        while i < len(src):
            c = src[i]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
            elif c == '"' and depth == 0:
                i = src.index('"', i + 1)
            elif c == ">" and depth == 0:
                break
            i += 1
        cn = re.search(r'className=(?:"([^"]*)"|\{`([^`]*)`\})',
                       src[m.end():i])
        classes = []
        if cn:
            classes = re.sub(r"\$\{[^}]*\}", " ",
                             cn.group(1) or cn.group(2) or "").split()
        out.append((m.group(1), classes))
    return out


def check_markup(old_src, new_src):
    """Every element that used to be styled by its tag must carry the class."""
    old_els, new_els = jsx_elements(old_src), jsx_elements(new_src)
    problems = []

    if len(old_els) != len(new_els):
        problems.append(f"element count changed {len(old_els)} -> "
                        f"{len(new_els)}; migration should only add classes")
        return problems, old_els, new_els

    for idx, ((otag, _), (ntag, ncls)) in enumerate(zip(old_els, new_els)):
        if otag != ntag:
            problems.append(f"element {idx}: tag changed {otag} -> {ntag}")
            continue
        need = REQUIRED_CLASS.get(ntag)
        if need and need not in ncls:
            problems.append(f"<{ntag}> #{idx} missing .{need} "
                            f"(has {ncls or 'no class'}) — lost its styling")
        if REQUIRED_CARD & set(ncls) and "card" not in ncls:
            problems.append(f"<{ntag}> #{idx} has {ncls} but not .card "
                            f"— lost its surface")
    return problems, old_els, new_els


def main():
    # encoding is explicit because the stage list uses ○ ● ▸ and Windows
    # would otherwise decode this as cp1252 and die.
    def git(ref):
        return subprocess.run(["git", "show", ref], capture_output=True,
                              text=True, encoding="utf-8", cwd="..",
                              check=True).stdout

    old_css = git(OLD_REF)
    new_css = inline_imports(NEW_ENTRY)

    old_rules, new_rules = parse(old_css), parse(new_css)
    old = computed(old_rules, collect_vars(old_rules))
    new = computed(new_rules, collect_vars(new_rules))

    # Re-key the new side the way the old side is keyed.
    mapped, consumed = dict(new), set()
    for old_sel, new_sels in list(ALIASES.items()) + list(COMPOSED.items()):
        merged, found = {}, False
        for ns in new_sels:
            if ("", ns) in new:
                merged.update(new[("", ns)])
                consumed.add(("", ns))
                found = True
        if found:
            mapped[("", old_sel)] = merged

    added = sorted(k for k in set(mapped) - set(old) if k not in consumed)
    removed = sorted(set(old) - set(mapped))
    changed = []
    for key in sorted(set(old) & set(mapped)):
        if old[key] != mapped[key]:
            diffs = []
            for prop in sorted(set(old[key]) | set(mapped[key])):
                a, b = old[key].get(prop), mapped[key].get(prop)
                if a != b:
                    diffs.append((prop, a, b))
            changed.append((key, diffs))

    print(f"old: {len(old_rules)} rules, {len(old)} selectors")
    print(f"new: {len(new_rules)} rules, {len(new)} selectors")
    print(f"     {len(ALIASES)} element selectors mapped to component "
          f"classes, {len(COMPOSED)} surfaces composed with .card\n")

    problems, old_els, new_els = check_markup(git("HEAD:frontend/src/App.jsx"),
                                              NEW_APP.read_text(encoding="utf-8"))
    print("=" * 74)
    print(f"MARKUP  ({len(new_els)} elements)")
    print("=" * 74)
    if problems:
        for p in problems:
            print(f"  FAIL {p}")
    else:
        counts = {}
        for tag, cls in new_els:
            if tag in REQUIRED_CLASS:
                counts[tag] = counts.get(tag, 0) + 1
        cards = sum(1 for _, c in new_els if "card" in c)
        print("  every element that was styled by its tag now carries its "
              "class:")
        print("   ", ", ".join(f"{n}x <{t}> .{REQUIRED_CLASS[t]}"
                               for t, n in sorted(counts.items())))
        print(f"    {cards}x .card")
    print()

    if changed:
        print("=" * 74)
        print(f"CHANGED  ({len(changed)} selectors) -- these alter rendering")
        print("=" * 74)
        for (ctx, sel), diffs in changed:
            print(f"\n  {ctx + ' ' if ctx else ''}{sel}")
            for prop, a, b in diffs:
                print(f"      {prop}\n        old: {a}\n        new: {b}")
    else:
        print("CHANGED: none. Every shared selector computes identically.")

    if removed:
        print("\n" + "=" * 74)
        print(f"REMOVED ({len(removed)}) -- selectors that no longer exist")
        print("=" * 74)
        for ctx, sel in removed:
            print(f"  {ctx + ' ' if ctx else ''}{sel}")

    if added:
        print("\n" + "=" * 74)
        print(f"ADDED ({len(added)}) -- new selectors; harmless only if they")
        print("match no element in the current markup")
        print("=" * 74)
        for ctx, sel in added:
            print(f"  {ctx + ' ' if ctx else ''}{sel}")

    return 1 if (changed or removed or problems) else 0


if __name__ == "__main__":
    sys.exit(main())
