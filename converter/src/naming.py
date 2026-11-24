"""Default output file names, shared by the command line and the web UI.

    <stem>_claude_ender3[_<material>]<profile suffix>[<variant>].3mf

The variant part names the settings that change the result, so variants of
one model do not overwrite each other:

    _<layer height>   custom layer height, e.g. _0.16
    _support          supports enabled
    _tree             tree supports (support_type=tree(...))
    _brim[<width>]    a brim; the width only when it is not the stock 5 mm
    _set<hash>        any other --set values (6 hex digits of their hash)

A plain run (no custom layer height, supports or --set) keeps the name it had
before variants were added.
"""
import hashlib
import os

from .config import GENERIC_DIRS

STOCK_BRIM_WIDTH = "5"


def _num(value):
    return f"{float(value):g}"


def variant_suffix(layer_height=None, support=False, extra=None):
    extra = dict(extra or {})
    parts = []
    if layer_height is not None:
        parts.append(_num(layer_height))
    if support:
        parts.append("support")
    support_type = extra.pop("support_type", None)
    if support_type is not None:
        if str(support_type).startswith("tree"):
            parts.append("tree")
        else:
            extra["support_type"] = support_type   # unusual value: goes into the hash
    brim_type = extra.pop("brim_type", None)
    brim_width = extra.pop("brim_width", None)
    if brim_type is not None and brim_type != "no_brim":
        width = "" if brim_width is None or _num(brim_width) == STOCK_BRIM_WIDTH else _num(brim_width)
        parts.append("brim" + width)
        if brim_type != "outer_only":
            extra["brim_type"] = brim_type
    elif brim_type is not None or brim_width is not None:
        if brim_type is not None:
            extra["brim_type"] = brim_type
        if brim_width is not None:
            extra["brim_width"] = brim_width
    if extra:
        text = ";".join(f"{k}={extra[k]}" for k in sorted(extra))
        parts.append("set" + hashlib.sha1(text.encode()).hexdigest()[:6])
    return "".join("_" + p for p in parts)


def output_name(stem, material, profile_name, profile, layer_height=None, support=False, extra=None):
    """File name (no folder) of the project for these settings."""
    mat = "" if material == "pla" else f"_{material}"
    suffix = profile.get("suffix", "_" + profile_name)
    return f"{stem}_claude_ender3{mat}{suffix}{variant_suffix(layer_height, support, extra)}.3mf"


def stem_for_inputs(inputs, count):
    """Stem from what the user gave: a folder name, one STL name, or '<first>_and_<n>_more'."""
    first = os.path.abspath(inputs[0]).rstrip(os.sep)
    if os.path.isdir(first):
        # "files" or "stl" says nothing and would collide between downloads: use the parent's name
        return os.path.basename(os.path.dirname(first) if os.path.basename(first).lower() in GENERIC_DIRS
                                else first)
    stem = os.path.splitext(os.path.basename(first))[0]
    return stem + (f"_and_{count - 1}_more" if count > 1 else "")
