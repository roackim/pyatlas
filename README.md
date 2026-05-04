# Pytalas

Aseprite to atlas tool — compact and metadata-aware.

Utility designed to simplify the 2D graphics production pipeline by packing sprite sheets into tight atlases with rich metadata export.

## Features

- **Compact atlas packing** — tight layout for sprite sheets.
- **Named animations** — extract animations directly from the atlas.
- **Layer ordering** — control draw order from Aseprite.
- **Frame time export** — per-frame timing information.
- **Meta layers** — hitboxes and points computed into consumable data for your game engine.

## Installation

### With pipx (recommended)

```sh
pipx install .
```

### Build a standalone binary

```sh
make build-binary
```

This produces a runnable binary at `./bin/atlas`.

## Usage

```sh
pyatlas -i <input_folder> -o <output_folder> -m <manifest_filename>
```

## Layer Naming Syntax

| Prefix | Meaning          | Example     |
|--------|------------------|-------------|
| `#`    | Animation layer  | `#jump`     |
| `@hb`  | Hitbox meta layer| `@hb.body`  |
| `@pt`  | Point meta layer | `@pt.origin`|

### Animation layers (`#<name>`)

Layers prefixed with `#` are exported as animation frames. Example: `#jump`, `#idle`.

### Hitbox meta layers (`@hb.<name>`)

The program computes the axis-aligned bounding box of non-transparent pixels for each frame. This allows defining hitboxes directly as pixel art — especially useful for per-frame hitboxes on complex characters or bosses.

### Point meta layers (`@pt.<name>`)

The program computes the barycenter (center of mass) of all non-transparent pixels per frame. Useful for anchor points, attach points, or origin references.
