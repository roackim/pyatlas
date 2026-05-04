from pathlib import Path
import re

from pyatlas.types import SpriteSheet


LUA_KEYWORDS = {
    "and", "break", "do", "else", "elseif", "end", "false", "for", "function",
    "goto", "if", "in", "local", "nil", "not", "or", "repeat", "return", "then",
    "true", "until", "while",
}


def _format_lua_key(key: str) -> str:
    if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key) and key not in LUA_KEYWORDS:
        return key
    return f'["{key}"]'


def _set_nested(tree: dict, dotted_key: str, value: dict):
    parts = dotted_key.split(".")
    cursor = tree
    for part in parts[:-1]:
        if part not in cursor:
            cursor[part] = {}
        cursor = cursor[part]
    cursor[parts[-1]] = value


def _is_flat_dict(value) -> bool:
    """True when every value in the dict is a primitive (number/string) or a flat list of primitives."""
    if not isinstance(value, dict) or not value:
        return False
    
    has_nested_dict = False
    for v in value.values():
        if isinstance(v, (int, float, str)):
            continue
        if isinstance(v, list) and all(isinstance(i, (int, float, str)) for i in v):
            continue
        # Allow one level of nesting: dict containing only primitives
        if isinstance(v, dict) and all(isinstance(vv, (int, float, str)) for vv in v.values()):
            has_nested_dict = True
            continue
        # Allow two levels of nesting if there's only 1 key at each level
        if isinstance(v, dict) and len(v) == 1:
            nested_val = next(iter(v.values()))
            if isinstance(nested_val, dict) and all(isinstance(vvv, (int, float, str)) for vvv in nested_val.values()):
                has_nested_dict = True
                continue
        return False
    
    # If there are nested dicts, only allow one-lining if there's exactly 1 entry
    if has_nested_dict and len(value) > 1:
        return False
    
    return True


def _to_lua(value, indent: int = 0) -> str:
    pad = " " * indent
    child_pad = " " * (indent + 2)

    if isinstance(value, dict):
        if _is_flat_dict(value):
            parts = ", ".join(
                f"{_format_lua_key(k)} = {_to_lua(value[k], 0)}"
                for k in sorted(value.keys())
            )
            return "{" + parts + "}"
        lines = ["{"]
        for key in sorted(value.keys()):
            lines.append(f"{child_pad}{_format_lua_key(key)} = {_to_lua(value[key], indent + 2)},")
        lines.append(f"{pad}}}")
        return "\n".join(lines)

    if isinstance(value, list):
        if not value:
            return "{}"
        return "{ " + ", ".join(_to_lua(v, indent) for v in value) + " }"

    if isinstance(value, str):
        return f'"{value}"'

    return str(value)


def _collapse_constants(value):
    """Recursively collapse dicts where all values are identical into {const = value}."""
    if not isinstance(value, dict):
        return value
    
    # First, recursively process all children
    processed = {k: _collapse_constants(v) for k, v in value.items()}
    
    # Check if all values in this dict are identical dicts (deep equality)
    if len(processed) > 1:
        values = list(processed.values())
        first = values[0]
        
        # Only collapse if all values are dicts and are identical
        if isinstance(first, dict) and all(v == first for v in values[1:]):
            return {"const": first}
    
    return processed


def export_regions_lua(sprite_sheet_list: list[SpriteSheet], output_dir: Path, manifest_name: str = "atlas_regions.lua"):
    output_dir.mkdir(parents=True, exist_ok=True)

    for sp in sprite_sheet_list:
        sp.compute()

    sorted_regions = []
    sorted_meta = []
    for sp in sprite_sheet_list:
        sorted_regions.extend(sp.region_items())
        sorted_meta.extend(sp.meta_items())
    # Do not sort regions alphabetically to keep Z order
    # sorted_regions.sort(key=lambda item: item[0])

    nested_regions = {}
    for key, layer in sorted_regions:
        _set_nested(
            nested_regions,
            key,
            {
                "x": layer.x,
                "y": layer.y,
                "w": layer.w,
                "h": layer.h,
                "n": layer.n,
                "durations_ms": layer.durations_ms,
            },
        )
    for key, val in sorted_meta:
        _set_nested(nested_regions, key, val)

    # Collapse constant values in metadata sections
    nested_regions = _collapse_constants(nested_regions)

    content = "return " + _to_lua({"atlas": "atlas_texture.png", "regions": nested_regions}, 0) + "\n"

    output_file = output_dir / manifest_name
    print(f"writing file {output_file}")
    with open(output_file, "w", encoding="utf-8") as file:
        file.write(content)
