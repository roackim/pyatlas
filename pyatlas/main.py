from pathlib import Path
from tempfile import TemporaryDirectory
import subprocess
import argparse

from pyatlas.compositor import compose_atlas
from pyatlas.lua_exporter import export_regions_lua
from pyatlas.parse_jsons import extract_sheet_infos
from pyatlas.solver import solve_placement
from pyatlas.types import AnimationLine, SpriteSheet


def normalize_key_part(value: str) -> str:
    lowered = value.strip().lower()
    cleaned = []
    for ch in lowered:
        if ch.isalnum() or ch == "_":
            cleaned.append(ch)
        elif ch in {" ", "-", "."}:
            cleaned.append("_")
    key = "".join(cleaned).strip("_")
    return key or "unnamed"


def build_sheet_key(input_dir: Path, source_file: Path) -> str:
    rel = source_file.relative_to(input_dir)
    parts = [normalize_key_part(p) for p in rel.parts[:-1]]
    parts.append(normalize_key_part(rel.stem))
    return ".".join([p for p in parts if p])


def find_aseprite_files(directory: Path) -> list[Path]:
    files = []
    for ext in ("*.ase", "*.aseprite"):
        files.extend(directory.rglob(ext))
    return sorted(files)


def split_sprite_sheet_regions(sprite: SpriteSheet) -> list[SpriteSheet]:
    """Split a parsed sheet into one packing unit per region to avoid cross-tag wasted width."""
    split_units = []

    for i, (region_key, region) in enumerate(sprite.layers.items()):
        unit = SpriteSheet(sprite.key_stem, sprite.source_path)

        unit_region = AnimationLine(region_key)
        unit_region.w = region.w
        unit_region.h = region.h
        unit_region.n = region.n
        unit_region.durations_ms = list(region.durations_ms)
        unit_region.source_frames = list(region.source_frames)
        unit_region.init_done = True
        unit_region.x = 0
        unit_region.y = 0

        unit.layers[region_key] = unit_region
        unit.total_width = region.w * region.n
        unit.total_height = region.h

        for j, src in enumerate(region.source_frames):
            dst_x = j * region.w
            unit.blit_ops.append((src[0], src[1], src[2], src[3], dst_x, 0))

        # Attach metadata to the first unit only to avoid duplicate exports
        if i == 0:
            unit.points = sprite.points
            unit.hitboxes = sprite.hitboxes
            unit.layer_order = sprite.layer_order

        split_units.append(unit)

    return split_units


def main(*args, **kwargs):
    
    parser = argparse.ArgumentParser(description='Atlas compositor')

    # Add the arguments
    parser.add_argument('-i', '--input_folder', type=str, help='The path to the input folder', required=True)
    parser.add_argument('-r', '--res_output_folder', type=str, help='The path to the resource output folder', default="output")
    parser.add_argument('-m', '--manifest_name', type=str, help='The lua manifest filename', default="atlas_regions.lua")
    

    # Execute the parse_args() method
    args = parser.parse_args()
    
    input_dir  = Path(args.input_folder)
    res_output_dir = Path(args.res_output_folder)
    manifest_name = args.manifest_name
    
    
    if not input_dir.is_dir():
        raise FileNotFoundError(f"input directory '{input_dir}' cannot be found")

    source_ase = find_aseprite_files(input_dir)
    if not source_ase:
        raise RuntimeError(f"no .ase/.aseprite files found in '{input_dir}'")
    
    with TemporaryDirectory() as tmp_dir:
        
        tmp_dir = Path(tmp_dir)
    
        sprite_sheets = []
        for ase in source_ase:
            rel = ase.relative_to(input_dir)
            tmp_base = (tmp_dir / rel).with_suffix("")
            tmp_base.parent.mkdir(parents=True, exist_ok=True)

            png = tmp_base.with_suffix(".png")
            json = tmp_base.with_suffix(".json")

            command = [
                "aseprite",
                "-b",
                "--all-layers",
                "--split-layers",
                "--list-tags",
                str(ase),
                "--sheet",
                str(png),
                "--data",
                str(json),
            ]
            subprocess.run(command, check=True)

            key_stem = build_sheet_key(input_dir, ase)
            sprite = extract_sheet_infos(json, png, key_stem=key_stem, source_stem=ase.stem)
            if not sprite.layers:
                print(f"\033[93mWARNING: skipping {ase}: no layers prefixed with '#'\033[0m")
                continue

            sprite_sheets.extend(split_sprite_sheet_regions(sprite))
            
        if not sprite_sheets:
            print("warning: no exportable layers found (layers must start with '#')")

        config = solve_placement(sprite_sheets)
        compose_atlas(sprite_sheets, config, res_output_dir)
        export_regions_lua(sprite_sheets, res_output_dir, manifest_name=manifest_name)
        

if __name__ == "__main__":
    main()