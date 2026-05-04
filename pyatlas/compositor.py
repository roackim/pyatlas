from pathlib import Path

from PIL import Image

from pyatlas.types import SpriteSheet


def build_filtered_source_image(sprite_sheet: SpriteSheet) -> Image.Image:
    source_image = Image.open(sprite_sheet.source_path)

    if not sprite_sheet.blit_ops:
        return Image.new("RGBA", (max(1, sprite_sheet.total_width), max(1, sprite_sheet.total_height)), (0, 0, 0, 0))

    filtered = Image.new("RGBA", (sprite_sheet.total_width, sprite_sheet.total_height), (0, 0, 0, 0))

    for src_x, src_y, src_w, src_h, dst_x, dst_y in sprite_sheet.blit_ops:
        frame = source_image.crop((src_x, src_y, src_x + src_w, src_y + src_h))
        filtered.paste(frame, (dst_x, dst_y))

    return filtered


def compose_atlas(sprite_sheet_list: list[SpriteSheet], config, output_dir: Path):
    chunks_w = config["chunks_w"]
    chunks_h = config["chunks_h"]
    chunk_size = config["chunk_size"]

    size = (chunks_w * chunk_size, chunks_h * chunk_size)
    atlas = Image.new("RGBA", size, (0, 0, 0, 0))

    for sp in sprite_sheet_list:
        source_image = build_filtered_source_image(sp)

        px = sp.solver_pos[0] * chunk_size
        py = sp.solver_pos[1] * chunk_size
        atlas_pos = (px, py)

        atlas.paste(source_image, atlas_pos)
        sp.atlas_pos = atlas_pos

    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / "atlas_texture.png"
    print(f"writing file {output_file}")
    atlas.save(output_file)
