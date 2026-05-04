
from pathlib import Path
import json
import re
from PIL import Image

from pyatlas.types import AnimationLine, SpriteSheet, PointMeta, HitboxMeta, normalize_key_part


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
    cleaned = raw_layer_name.lstrip("#")
    if cleaned.startswith("@pt."):
        cleaned = cleaned[4:]
    elif cleaned.startswith("@hb."):
        cleaned = cleaned[4:]
    return normalize_key_part(cleaned)

def collect_export_layers(entries: list[tuple[str, dict]], source_stem: str) -> set[str]:
    export_layers = set()
    for filename, _ in entries:
        raw_layer_name = extract_layer_name_raw(filename, source_stem)
        if raw_layer_name.startswith("#") or raw_layer_name.startswith("@pt.") or raw_layer_name.startswith("@hb."):
            export_layers.add(normalize_layer_key(raw_layer_name))
    return export_layers


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

def get_json_content(json_file_path):
    with open(json_file_path, 'r') as json_file:
        json_content = json.load(json_file)
    return json_content


def extract_sheet_infos(json_path: str, png_path, key_stem: str, source_stem: str) -> SpriteSheet:
    json_content = get_json_content(json_path)
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
        is_pt = raw_layer_name.startswith("@pt.")
        is_hb = raw_layer_name.startswith("@hb.")
        if not (raw_layer_name.startswith("#") or is_pt or is_hb):
            continue

        layer_name = normalize_layer_key(raw_layer_name)
        frame_number = extract_frame_number(filename)
        matched_tags = matching_tags(frame_number, frame_tags)

        is_auto_layer = has_auto and layer_name == "auto"
        if is_auto_layer:
            # Collapse layer segment: file.tag or just file when no tags.
            region_keys = matched_tags if matched_tags else [""]
        else:
            region_keys = [f"{tag}.{layer_name}" for tag in matched_tags] if matched_tags else [layer_name]

        ld = frame_info["frame"]
        rect = (int(ld["x"]), int(ld["y"]), int(ld["w"]), int(ld["h"]))

        if is_pt or is_hb:
            for region_key in region_keys:
                if is_pt:
                    if region_key not in sprite_sheet.points:
                        sprite_sheet.points[region_key] = PointMeta(region_key)
                    
                    found_x, found_y, count = 0, 0, 0
                    if png_img and rect[2] > 0 and rect[3] > 0:
                        crop = png_img.crop((rect[0], rect[1], rect[0]+rect[2], rect[1]+rect[3]))
                        pixels = crop.load()
                        for cy in range(rect[3]):
                            for cx in range(rect[2]):
                                if pixels[cx, cy][3] > 127:  # A > 127
                                    # Add pixel center (offset by +0.5)
                                    found_x += cx + 0.5
                                    found_y += cy + 0.5
                                    count += 1
                    
                    # Calculate mean/average position of pixel centers
                    out_x = found_x / count if count > 0 else 0.0
                    out_y = found_y / count if count > 0 else 0.0
                    sprite_sheet.points[region_key].add_frame(out_x, out_y)
                    
                else: # is_hb
                    if region_key not in sprite_sheet.hitboxes:
                        sprite_sheet.hitboxes[region_key] = HitboxMeta(region_key)
                        
                    min_x, min_y, max_x, max_y = 99999, 99999, -1, -1
                    if png_img and rect[2] > 0 and rect[3] > 0:
                        crop = png_img.crop((rect[0], rect[1], rect[0]+rect[2], rect[1]+rect[3]))
                        pixels = crop.load()
                        for cy in range(rect[3]):
                            for cx in range(rect[2]):
                                if pixels[cx, cy][3] > 127:
                                    if cx < min_x: min_x = cx
                                    if cy < min_y: min_y = cy
                                    if cx > max_x: max_x = cx
                                    if cy > max_y: max_y = cy
                    
                    if min_x > max_x:  # no pixels
                        min_x, min_y, max_x, max_y = 0, 0, 0, 0
                        
                    # w = max - min + 1 (since pixel coords are inclusive)
                    out_w = (max_x - min_x + 1) if max_x >= min_x else 0
                    out_h = (max_y - min_y + 1) if max_y >= min_y else 0
                    sprite_sheet.hitboxes[region_key].add_frame(min_x, min_y, out_w, out_h)
            continue

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
    
    return sprite_sheet