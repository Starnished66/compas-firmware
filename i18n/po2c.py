#!/usr/bin/env python3
"""Generate src/ui/text/i18n/i18n_catalog.c (the language list) and one
i18n_catalog_<code>.c table per language from po/*.po.

Usage: po2c.py [--check] [-o OUTPUT_DIR] [PO_DIR]

Skips fuzzy and untranslated entries. Exits non-zero when a translation's
printf conversions differ from the English text (count, order, type).
Stale i18n_catalog_*.c files with no po file are deleted.
With --check nothing is written; the output files must already be up to date.
"""
import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# The catalog is generated into the compas-player checkout.
ROOT = os.path.abspath(os.environ.get("COMPAS_PLAYER_DIR", os.path.join(HERE, "..", "..", "compas-player")))

CONV_RE = re.compile(r"%(?:\d+\$)?[-+ #0']*(?:\*|\d+)?(?:\.(?:\*|\d+))?(hh|h|ll|l|j|z|t|L)?([diouxXeEfFgGaAcspn%])")


def unquote(s):
    s = s.strip()
    assert s.startswith('"') and s.endswith('"'), s
    out = []
    body = s[1:-1]
    i = 0
    esc = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\", "a": "\a", "b": "\b", "f": "\f", "v": "\v"}
    while i < len(body):
        c = body[i]
        if c == "\\" and i + 1 < len(body):
            d = body[i + 1]
            if d in esc:
                out.append(esc[d])
                i += 2
                continue
            m = re.match(r"[0-7]{1,3}", body[i + 1:])
            if m:
                out.append(chr(int(m.group(0), 8)))
                i += 1 + len(m.group(0))
                continue
        out.append(c)
        i += 1
    return "".join(out)


def parse_po(path):
    """Returns (header dict, entries). entry: dict ctx,id,plural,str(list),fuzzy."""
    entries = []
    cur = None
    field = None
    fuzzy_next = False

    def flush():
        nonlocal cur
        if cur is not None and cur.get("id") is not None:
            entries.append(cur)
        cur = None

    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.rstrip("\n")
            if line.startswith("#,"):
                if cur is not None and cur.get("str"):
                    flush()
                fuzzy_next = "fuzzy" in line
                if cur is None:
                    cur = {"ctx": None, "id": None, "plural": None, "str": {}, "fuzzy": False}
                cur["fuzzy"] = cur["fuzzy"] or fuzzy_next
                continue
            if line.startswith("#") or not line.strip():
                if line.strip() == "" and cur is not None and cur.get("str"):
                    flush()
                continue
            m = re.match(r"(msgctxt|msgid_plural|msgid|msgstr(?:\[(\d+)\])?)\s+(\".*)$", line)
            if m:
                key = m.group(1)
                val = unquote(m.group(3))
                if key == "msgctxt" or key == "msgid":
                    if cur is not None and cur.get("str"):
                        flush()
                    if cur is None:
                        cur = {"ctx": None, "id": None, "plural": None, "str": {}, "fuzzy": False}
                if key == "msgctxt":
                    cur["ctx"] = val
                    field = ("ctx",)
                elif key == "msgid":
                    cur["id"] = val
                    field = ("id",)
                elif key == "msgid_plural":
                    cur["plural"] = val
                    field = ("plural",)
                else:
                    idx = int(m.group(2)) if m.group(2) is not None else 0
                    cur["str"][idx] = val
                    field = ("str", idx)
                continue
            if line.startswith('"'):
                val = unquote(line)
                if field[0] == "str":
                    cur["str"][field[1]] += val
                else:
                    cur[field[0]] += val
                continue
            raise SystemExit("%s: cannot parse line: %s" % (path, line))
    flush()
    header = {}
    out = []
    for e in entries:
        if e["id"] == "" and e["ctx"] is None:
            for hl in e["str"].get(0, "").split("\n"):
                if ":" in hl:
                    k, v = hl.split(":", 1)
                    header[k.strip()] = v.strip()
        else:
            out.append(e)
    return header, out


def conversions(s):
    return [(m.group(1) or "", m.group(2)) for m in CONV_RE.finditer(s) if m.group(2) != "%"]


def check_entry(path, e, errors):
    ref = [conversions(e["id"])]
    if e["plural"] is not None:
        ref.append(conversions(e["plural"]))
    for idx, s in e["str"].items():
        if not s:
            continue
        got = conversions(s)
        if got not in ref:
            errors.append("%s: printf mismatch for %r (form %d): %r vs %r" % (path, e["id"], idx, got, ref))


def c_str(s):
    out = ['"']
    for ch in s:
        if ch == '"':
            out.append('\\"')
        elif ch == "\\":
            out.append("\\\\")
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\t":
            out.append("\\t")
        elif ord(ch) < 0x20 or ord(ch) == 0x7f:
            out.append("\\%03o" % ord(ch))
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def build(po_dir):
    errors = []
    langs = []
    for path in sorted(glob.glob(os.path.join(po_dir, "*.po"))):
        header, entries = parse_po(path)
        code = header.get("Language") or os.path.splitext(os.path.basename(path))[0]
        name = header.get("X-Native-Name") or code
        table = {}
        for e in entries:
            check_entry(path, e, errors)
            if e["fuzzy"]:
                continue
            forms = [e["str"][i] for i in sorted(e["str"])]
            if not forms or not all(forms):
                continue
            key = (e["ctx"] + "\x04" if e["ctx"] is not None else "") + e["id"]
            table[key] = forms
        langs.append((code, name, table))
    return langs, errors


def ident(code):
    return re.sub(r"\W", "_", code)


def render_lang(code, table):
    out = ["/* Generated by i18n/po2c.py from i18n/po/%s.po in compas-firmware. Do not edit. */" % code,
           '#include "i18n.h"', "",
           "const i18n_entry_t i18n_entries_%s[] = {" % ident(code)]
    for k in sorted(table, key=lambda k: k.encode("utf-8")):
        forms = table[k]
        out.append("    {%s, (const char * const[]){%s}, %d}," % (c_str(k), ", ".join(c_str(s) for s in forms), len(forms)))
    if not table:
        out.append("    {0, 0, 0}")
    out.append("};")
    out.append("")
    return "\n".join(out)


def render_list(langs):
    out = ["/* Generated by i18n/po2c.py from the po/ catalogs in compas-firmware. Do not edit. */",
           '#include "i18n.h"', ""]
    for code, name, table in langs:
        out.append("extern const i18n_entry_t i18n_entries_%s[];" % ident(code))
    out.append("")
    out.append("const i18n_lang_t i18n_catalog_langs[] = {")
    for code, name, table in langs:
        out.append("    {%s, %s, i18n_entries_%s, %d}," % (c_str(code), c_str(name), ident(code), len(table)))
    if not langs:
        out.append("    {0, 0, 0, 0}")
    out.append("};")
    out.append("const size_t i18n_catalog_lang_count = %d;" % len(langs))
    out.append("")
    return "\n".join(out)


def render(langs):
    """Returns {file name: text} for the language list and every language table."""
    files = {"i18n_catalog.c": render_list(langs)}
    for code, name, table in langs:
        files["i18n_catalog_%s.c" % code] = render_lang(code, table)
    return files


def main(argv):
    check = False
    output = os.path.join(ROOT, "src", "ui", "text", "i18n")
    po_dir = os.path.join(HERE, "po")
    args = argv[1:]
    while args:
        a = args.pop(0)
        if a == "--check":
            check = True
        elif a in ("-h", "--help"):
            print("Usage: po2c.py [--check] [-o OUTPUT_DIR] [PO_DIR]")
            return 0
        elif a == "-o":
            if not args:
                sys.stderr.write("-o requires an output directory\n")
                return 2
            output = args.pop(0)
        elif a.startswith("-"):
            sys.stderr.write("Unknown option: %s\n" % a)
            return 2
        else:
            po_dir = a
    if not os.path.isdir(po_dir):
        sys.stderr.write("PO directory does not exist: %s\n" % po_dir)
        return 2
    langs, errors = build(po_dir)
    if errors:
        sys.stderr.write("\n".join(errors) + "\n")
        return 1
    files = render(langs)
    orphans = []
    if os.path.isdir(output):
        orphans = sorted(fn for fn in os.listdir(output)
                         if re.match(r"i18n_catalog_.*\.c$", fn) and fn not in files)
    if check:
        bad = False
        for fn in sorted(files):
            path = os.path.join(output, fn)
            try:
                with open(path, encoding="utf-8") as f:
                    cur = f.read()
            except OSError:
                cur = None
            if cur != files[fn]:
                sys.stderr.write("%s is %s; run po2c.py\n" % (path, "missing" if cur is None else "out of date"))
                bad = True
        for fn in orphans:
            sys.stderr.write("%s has no po file; run po2c.py\n" % os.path.join(output, fn))
            bad = True
        return 1 if bad else 0
    os.makedirs(output, exist_ok=True)
    for fn, text in files.items():
        path = os.path.join(output, fn)
        try:
            with open(path, encoding="utf-8") as f:
                if f.read() == text:
                    continue
        except OSError:
            pass
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    for fn in orphans:
        os.remove(os.path.join(output, fn))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
