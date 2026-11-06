"""Pictures in a recipe (PROPOSAL, 3 Nov 2026; recipe-pictures-design.md): an icon and a few screenshots, checked
strictly before anyone shows them. An SVG is a program in disguise unless it's held to plain shapes, so this is an
allow-list: only drawing elements and attributes, links only inside the file (#id), no scripts, no styles that
fetch, no DOCTYPE. PNG/WebP screenshots are checked by their real header and size, never by their name."""

import re, struct
import xml.etree.ElementTree as ET

MAX_ICON = 32 * 1024
MAX_SHOT = 400 * 1024
MAX_SHOTS = 4
SVG_NS = "{http://www.w3.org/2000/svg}"
XLINK = "{http://www.w3.org/1999/xlink}href"
ELEMENTS = {"svg", "g", "path", "circle", "ellipse", "rect", "line", "polyline", "polygon", "defs", "linearGradient",
            "radialGradient", "stop", "clipPath", "mask", "title", "desc", "use", "symbol", "style"}   # <style>: checked below
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
ATTRS = {"id", "class", "viewBox", "width", "height", "x", "y", "x1", "y1", "x2", "y2", "cx", "cy", "r", "rx", "ry", "fx", "fy",
         "d", "points", "transform", "fill", "fill-rule", "fill-opacity", "stroke", "stroke-width", "stroke-linecap",
         "stroke-linejoin", "stroke-miterlimit", "stroke-dasharray", "stroke-dashoffset", "stroke-opacity", "opacity",
         "clip-path", "clip-rule", "mask", "offset", "stop-color", "stop-opacity", "gradientUnits", "gradientTransform",
         "spreadMethod", "preserveAspectRatio", "version", "style", "href", "maskUnits", "maskContentUnits",
         "clipPathUnits", "xml:space", "color", "display", "visibility", "paint-order", "vector-effect", "overflow",
         "isolation", "mix-blend-mode", "shape-rendering", "enable-background"}
URL_OK = re.compile(r"url\(\s*#[A-Za-z0-9_.:-]+\s*\)")
STYLE_BAD = re.compile(r"(?i)@import|expression\s*\(|javascript:|url\(|behavior\s*:|-moz-binding")


def check_svg(data):
    """Errors (empty = fine) for an SVG icon."""
    err = []
    if len(data) > MAX_ICON:
        return [f"icon: larger than {MAX_ICON // 1024} KiB"]
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return ["icon: not UTF-8 text"]
    if re.search(r"(?i)<!DOCTYPE|<!ENTITY|<\?xml-stylesheet", text):
        return ["icon: no DOCTYPE, entities or style sheets"]
    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        return [f"icon: not a well-formed SVG ({e})"]
    for el in root.iter():
        tag = el.tag
        if not tag.startswith(SVG_NS) and tag != "svg":
            err.append(f"icon: element {tag[:60]} isn't SVG"); continue
        name = tag[len(SVG_NS):] if tag.startswith(SVG_NS) else tag
        if name not in ELEMENTS:
            err.append(f"icon: <{name}> isn't allowed (only plain shapes)")
        for k, v in el.attrib.items():
            if k == XLINK:
                k = "href"
            elif k == XML_SPACE:
                continue
            elif k.startswith("{"):
                err.append(f"icon: attribute {k[:60]} isn't allowed"); continue
            if k not in ATTRS:
                err.append(f"icon: attribute {k[:40]} on <{name}> isn't allowed")
            elif k == "href" and not re.fullmatch(r"#[A-Za-z0-9_.:-]+", v):
                err.append(f"icon: a link may only point inside the file ({v[:40]!r})")
            elif k == "style" and STYLE_BAD.search(URL_OK.sub("", v)):
                err.append(f"icon: a style that fetches or runs something ({v[:40]!r})")
            elif "url(" in v and STYLE_BAD.search(URL_OK.sub("", v)):
                err.append(f"icon: {k} points outside the file ({v[:40]!r})")
        if name == "style" and STYLE_BAD.search(URL_OK.sub("", el.text or "")):
            err.append("icon: a <style> that fetches or runs something")
        if name == "style" and len(el):
            err.append("icon: <style> may only hold text")
    if root.tag not in (SVG_NS + "svg", "svg"):
        err.append("icon: the file must start with <svg>")
    return sorted(set(err))


def image_size(data):
    """(kind, width, height) from a PNG or WebP header, or None."""
    if data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR":
        w, h = struct.unpack(">II", data[16:24]); return "png", w, h
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        c = data[12:16]
        if c == b"VP8 " and len(data) >= 30:
            w, h = struct.unpack("<HH", data[26:30]); return "webp", w & 0x3FFF, h & 0x3FFF
        if c == b"VP8L" and len(data) >= 25:
            b = int.from_bytes(data[21:25], "little"); return "webp", (b & 0x3FFF) + 1, ((b >> 14) & 0x3FFF) + 1
        if c == b"VP8X" and len(data) >= 30:
            return "webp", int.from_bytes(data[24:27], "little") + 1, int.from_bytes(data[27:30], "little") + 1
    return None


def check_shot(data, name):
    err = []
    if len(data) > MAX_SHOT:
        err.append(f"{name}: larger than {MAX_SHOT // 1024} KiB")
    k = image_size(data)
    if not k:
        return err + [f"{name}: not a PNG or WebP picture"]
    kind, w, h = k
    if not (640 <= w <= 1920 and 360 <= h <= 1200):
        err.append(f"{name}: {w}×{h} — between 640×360 and 1920×1200, please")
    if not name.endswith("." + kind):
        err.append(f"{name}: is a {kind.upper()} — name it .{kind}")
    return err


def check_icon(data, name):
    """Errors for an icon file: an SVG held to the allow-list, or a square PNG of 128–512 px."""
    if name.endswith(".svg"):
        return check_svg(data)
    err = []
    if len(data) > MAX_ICON:
        err.append(f"icon: larger than {MAX_ICON // 1024} KiB")
    k = image_size(data)
    if not k or k[0] != "png":
        return err + ["icon: not a PNG picture"]
    _, w, h = k
    if w != h or not 128 <= w <= 512:
        err.append(f"icon: {w}×{h} — a square of 128 to 512 px, please")
    return err


def check_file(path, data):
    """Errors for one picture file of a recipe, by its place in the recipe folder ('icon.svg', 'screenshots/2.webp')."""
    if path.startswith("icon."):
        return check_icon(data, path)
    if path.startswith("screenshots/"):
        return check_shot(data, path)
    return [f"{path}: not a picture a recipe may hold"]
