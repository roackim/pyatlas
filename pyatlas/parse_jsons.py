
from pathlib import Path
import json
import re
from PIL import Image

from pyatlas.types import AnimationLine, SpriteSheet, PointMeta, HitboxMeta, normalize_key_part
from pyatlas.core import log


# Metadata layers: "@hb.<label>" -> box, "@pt.<label>" -> point. The label is kept verbatim; dots are part of it.
BOX_PREFIX = "@hb."
POINT_PREFIX = "@pt."
LABEL_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)*$")

# Labels named by the build-time sanity warnings (the exporter gives them no other special treatment)
SOLIDBOX_LABEL = "solidbox"     # warn when present on some frames of a state but not all
ORIGIN_LABEL = "origin"         # warn when a state has metadata but no such point (or "origin.<variant>")


def extract_layer_name_raw(filename: str, source_stem: str) -> str:
    stem = Path(filename).stem

    match_paren = re.search(r"\(([^)]+)\)", stem)
    if match_paren:
        return match_paren.group(1).strip()

    stem = re.sub(r"[ _-]?\d+$", "", stem)
    source_prefix = source_stem
    if stem.lower().startswith(source_prefix.lower()):
        stem = stem[len(source_prefix):].lstrip(" _-.")

    return (stem or source_stem).strip()


def normalize_layer_key(raw_layer_name: str) -> str:
    return normalize_key_part(raw_layer_name.lstrip("#"))


def parse_meta_layer(raw_layer_name: str, where) -> tuple[str, str] | None:
    """("boxes" | "points", label) for an '@' layer, None for any other layer. Raises on malformed '@' layers."""
    if not raw_layer_name.startswith("@"):
        return None
    for kind, prefix in (("boxes", BOX_PREFIX), ("points", POINT_PREFIX)):
        if raw_layer_name.startswith(prefix):
            label = raw_layer_name[len(prefix):]
            if not LABEL_PATTERN.match(label):
                raise ValueError(
                    f"{where}: layer '{raw_layer_name}' has an invalid label '{label}' "
                    f"(expected letters, digits, '_' and '.'-separated parts)"
                )
            return kind, label
    raise ValueError(
        f"{where}: unrecognized metadata layer '{raw_layer_name}' (expected '{BOX_PREFIX}<label>' or '{POINT_PREFIX}<label>')"
    )


def validate_meta_layers(duplicate_frame_keys: list[str], source_stem: str, where):
    """
    A label may be defined by only one layer per kind. Two layers with the same name export frames
    with the same filename, which json.load would silently merge, so duplicates are caught at parse time.
    """
    for filename in duplicate_frame_keys:
        raw_layer_name = extract_layer_name_raw(filename, source_stem)
        if parse_meta_layer(raw_layer_name, where) is not None:
            raise ValueError(f"{where}: more than one layer named '{raw_layer_name}'")


def collect_export_layers(entries: list[tuple[str, dict]], source_stem: str) -> set[str]:
    export_layers = set()
    for filename, _ in entries:
        raw_layer_name = extract_layer_name_raw(filename, source_stem)
        if raw_layer_name.startswith("#"):
            export_layers.add(normalize_layer_key(raw_layer_name))
    return export_layers


def _opaque_pixels(png_img, rect):
    """Yield (x, y) of pixels with alpha > 127 inside rect, relative to its top-left."""
    if png_img is None or rect[2] <= 0 or rect[3] <= 0:
        return
    crop = png_img.crop((rect[0], rect[1], rect[0] + rect[2], rect[1] + rect[3]))
    pixels = crop.load()
    for cy in range(rect[3]):
        for cx in range(rect[2]):
            if pixels[cx, cy][3] > 127:
                yield cx, cy


def compute_point(png_img, rect):
    """Mean of the opaque pixel centres (+0.5), unrounded; (None, None) when the frame is empty."""
    found_x, found_y, count = 0.0, 0.0, 0
    for cx, cy in _opaque_pixels(png_img, rect):
        found_x += cx + 0.5
        found_y += cy + 0.5
        count += 1
    if count == 0:
        return None, None
    return found_x / count, found_y / count


def compute_box(png_img, rect):
    """Inclusive bounding box (x, y, w, h) of the opaque pixels; all None when the frame is empty."""
    min_x, min_y, max_x, max_y = 99999, 99999, -1, -1
    for cx, cy in _opaque_pixels(png_img, rect):
        if cx < min_x: min_x = cx
        if cy < min_y: min_y = cy
        if cx > max_x: max_x = cx
        if cy > max_y: max_y = cy
    if min_x > max_x:
        return None, None, None, None
    return min_x, min_y, max_x - min_x + 1, max_y - min_y + 1


def warn_suspicious_states(sprite_sheet: SpriteSheet):
    """Build-time hints for likely authoring mistakes; never blocks the export."""
    for state in sorted(set(sprite_sheet.boxes) | set(sprite_sheet.points)):
        where = f"{sprite_sheet.key_stem}.{state}" if state else sprite_sheet.key_stem

        solid = sprite_sheet.boxes.get(state, {}).get(SOLIDBOX_LABEL)
        if solid is not None:
            present = [f is not None for f in solid.frames]
            if any(present) and not all(present):
                missing = [i + 1 for i, p in enumerate(present) if not p]
                log.warning(f"{where}: '{BOX_PREFIX}{SOLIDBOX_LABEL}' is absent on frames {missing}")

        # "origin" or any variant of it ("origin.floor", "origin.ceil", ...) counts
        has_origin = any(
            (label == ORIGIN_LABEL or label.startswith(ORIGIN_LABEL + ".")) and any(f is not None for f in pt.frames)
            for label, pt in sprite_sheet.points.get(state, {}).items()
        )
        if not has_origin:
            log.warning(f"{where}: no '{POINT_PREFIX}{ORIGIN_LABEL}' or '{POINT_PREFIX}{ORIGIN_LABEL}.<variant>' point")


def extract_frame_number(filename: str):
    stem = Path(filename).stem
    match = re.search(r"(\d+)$", stem)
    if match:
        return int(match.group(1))
    return 0


def extract_frame_tags(json_content: dict) -> list[tuple[str, int, int]]:
    tags = []
    for tag in json_content.get("meta", {}).get("frameTags", []):
        tag_name = normalize_key_part(tag.get("name", ""))
        frame_from = int(tag.get("from", 0))
        frame_to = int(tag.get("to", frame_from))
        tags.append((tag_name, frame_from, frame_to))
    return tags


def matching_tags(frame_number: int, tags: list[tuple[str, int, int]]) -> list[str]:
    result = []
    for tag_name, frame_from, frame_to in tags:
        if frame_from <= frame_number <= frame_to:
            result.append(tag_name)
    return result

def get_json_content(json_file_path, duplicate_keys: list | None = None):
    """Load a JSON file; keys seen more than once in an object are appended to duplicate_keys (last one wins)."""
    def keep_last(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj and duplicate_keys is not None:
                duplicate_keys.append(key)
            obj[key] = value
        return obj

    with open(json_file_path, 'r') as json_file:
        json_content = json.load(json_file, object_pairs_hook=keep_last)
    return json_content


def extract_sheet_infos(json_path: str, png_path, key_stem: str, source_stem: str) -> SpriteSheet:
    duplicate_keys = []
    json_content = get_json_content(json_path, duplicate_keys)
    validate_meta_layers(duplicate_keys, source_stem, json_path)
    sprite_sheet = SpriteSheet(key_stem, png_path)
    frame_tags = extract_frame_tags(json_content)
    
    data = json_content["frames"]

    entries = []
    if isinstance(data, dict):
        entries = list(data.items())
    elif isinstance(data, list):
        entries = [(frame.get("filename", "frame_0"), frame) for frame in data]
        
    png_img = None
    if Path(png_path).exists():
        png_img = Image.open(png_path).convert("RGBA")

    # Order layers by meta appearance first
    json_meta_layers = json_content.get("meta", {}).get("layers", [])
    
    # Store ordered visual layers in sprite_sheet.layer_order
    for mlayer in reversed(json_meta_layers):
        mname = mlayer.get("name", "")
        # Aseprite might not show # in name. But let's just grab everything and strip #
        if mname.startswith("#"):
            sprite_sheet.layer_order.append(normalize_layer_key(mname))

    export_layers = collect_export_layers(entries, source_stem)
    has_auto = "auto" in export_layers
    
    # Filter out metadata layers (@pt. and @hb.) when checking for #auto exclusivity
    # since metadata layers don't create visual sprite layers
    visual_layers = set()
    for filename, _ in entries:
        raw_layer_name = extract_layer_name_raw(filename, source_stem)
        if raw_layer_name.startswith("#"):
            visual_layers.add(normalize_layer_key(raw_layer_name))
    
    if has_auto and len(visual_layers) > 1:
        raise ValueError(
            f"{json_path}: '#auto' layer is only valid when it is the only visual export layer (excluding metadata layers)"
        )

    for filename, frame_info in entries:
        raw_layer_name = extract_layer_name_raw(filename, source_stem)
        meta_layer = parse_meta_layer(raw_layer_name, json_path)
        if not (raw_layer_name.startswith("#") or meta_layer):
            continue

        frame_number = extract_frame_number(filename)
        matched_tags = matching_tags(frame_number, frame_tags)

        ld = frame_info["frame"]
        rect = (int(ld["x"]), int(ld["y"]), int(ld["w"]), int(ld["h"]))

        if meta_layer:
            # Metadata belongs to the state: the frame tag, or "" for an untagged file
            kind, label = meta_layer
            states = matched_tags if matched_tags else [""]
            if kind == "points":
                value = compute_point(png_img, rect)
                store, meta_cls = sprite_sheet.points, PointMeta
            else:
                value = compute_box(png_img, rect)
                store, meta_cls = sprite_sheet.boxes, HitboxMeta
            for state in states:
                per_label = store.setdefault(state, {})
                if label not in per_label:
                    per_label[label] = meta_cls(label)
                per_label[label].add_frame(*value)
            continue

        layer_name = normalize_layer_key(raw_layer_name)
        is_auto_layer = has_auto and layer_name == "auto"
        if is_auto_layer:
            # Collapse layer segment: file.tag or just file when no tags.
            region_keys = matched_tags if matched_tags else [""]
        else:
            region_keys = [f"{tag}.{layer_name}" for tag in matched_tags] if matched_tags else [layer_name]

        if layer_name not in sprite_sheet.layer_order:
            sprite_sheet.layer_order.append(layer_name)

        for region_key in region_keys:
            if region_key not in sprite_sheet.layers:
                sprite_sheet.layers[region_key] = AnimationLine(region_key)

            layer_data = sprite_sheet.layers[region_key]

            if not layer_data.init_done:
                layer_data.w = int(ld["w"])
                layer_data.h = int(ld["h"])
                layer_data.init_done = True

            layer_data.n += 1
            layer_data.durations_ms.append(int(frame_info.get("duration", 100)))
            layer_data.source_frames.append(rect)
    
    total_width = 0
    total_height = 0

    for layer_name in sorted(sprite_sheet.layers.keys()):
        layer = sprite_sheet.layers[layer_name]
        layer.x = 0
        layer.y = total_height

        row_width = layer.w * layer.n
        total_width = max(total_width, row_width)

        for i, src in enumerate(layer.source_frames):
            dst_x = i * layer.w
            dst_y = layer.y
            sprite_sheet.blit_ops.append((src[0], src[1], src[2], src[3], dst_x, dst_y))

        total_height += layer.h

    sprite_sheet.total_width = total_width
    sprite_sheet.total_height = total_height

    warn_suspicious_states(sprite_sheet)
    
    return sprite_sheet