from pathlib import Path


def normalize_key_part(value: str) -> str:
    stripped = value.strip()
    cleaned = []
    for ch in stripped:
        if ch.isalnum() or ch == "_":
            cleaned.append(ch)
        elif ch in {" ", "-", "."}:
            cleaned.append("_")
    key = "".join(cleaned).strip("_")
    return key or "unnamed"


class AnimationLine:
    def __init__(self, name: str):
        self.name = normalize_key_part(name)
        self.x = 0 # start position on X axis in px
        self.y = 0 # start position on Y axis in px
        self.w = 0 # size of a single cell on X axis in px
        self.h = 0 # size of a single cell on Y axis in px
        self.n = 0 # number of cells contained in the animation
        self.durations_ms = []
        self.source_frames = []
        self.init_done = False
    
    def apply_offset(self, offset):
        self.x += offset[0]
        self.y += offset[1]
    
    def __str__(self):
        return f"  <{self.name}> x: {self.x}, y: {self.y}, w: {self.w}, h: {self.h}, n: {self.n}"
        
    def to_json(self):
        return f"\"{self.name}\": ".ljust(24) + f"\t\t{{\"x\": {self.x:4d}, \"y\": {self.y:4d}, \"w\": {self.w:3d}, \"h\": {self.h:3d}, \"n\": {self.n:2d}}}"
    
    def to_cpp_init(self, section: str):
        # return tupple of (bool, str)
        # false, true = sprite, anim 
        if self.n == 1:
            return f"\tres::sprite::assign(\"{section}::{self.name}\", vect2i({self.x}, {self.y}), vect2i({self.w}, {self.h}));"
        else:
            return f"\tres::anim::assign(\"{section}::{self.name}\", vect2i({self.x}, {self.y}), vect2i({self.w}, {self.h}), {self.n}, sf::milliseconds(100), true);"
    
    def to_cpp_alias(self, section: str):
        string = f"\t\tconst std::string {self.name} = \"{section}::{self.name}\";"
        return (int(self.n != 1), string)
        

class PointMeta:
    """Per-frame point of one label in one state. None marks a frame where the label is absent."""
    def __init__(self, label: str):
        self.label = label
        self.frames = []

    def add_frame(self, cx, cy):
        if cx is None:
            self.frames.append(None)
        else:
            self.frames.append({"x": cx, "y": cy})

class HitboxMeta:
    """Per-frame box of one label in one state. None marks a frame where the label is absent."""
    def __init__(self, label: str):
        self.label = label
        self.frames = []

    def add_frame(self, x, y, w, h):
        if x is None:
            self.frames.append(None)
        else:
            self.frames.append({"x": x, "y": y, "w": w, "h": h})


def wrap_frames(frames: list):
    """
    {const = V} when present with the same value on every frame,
    {frames = {[i] = V}} (1-based, sparse) otherwise, None when absent on every frame.
    """
    if frames and frames[0] is not None and all(f == frames[0] for f in frames[1:]):
        return {"const": frames[0]}
    sparse = {i + 1: f for i, f in enumerate(frames) if f is not None}
    if not sparse:
        return None
    return {"frames": sparse}


class SpriteSheet:
    def __init__(self, key_stem: str, source_path: Path):
        self.key_stem = key_stem
        self.layers = {}
        self.layer_order = []  
        self.points = {}    # state -> label -> PointMeta ("" state = untagged file)
        self.boxes = {}     # state -> label -> HitboxMeta
        self.total_width  = 0
        self.total_height = 0
        self.blit_ops = []
        
        self.source_path = source_path # path to the png spritesheet containing all
        self.solver_pos = None
        self.atlas_pos = None
        
        self.computed = False
        
    def compute(self):
        if not self.computed:
            for layer in self.layers:    
                self.layers[layer].apply_offset(self.atlas_pos)
            self.computed = True
    
    def __str__(self):
        mess = f"[{self.key_stem}]: width: {self.total_width}, height: {self.total_height}"
        for layer in self.layers:
            mess += "\n" + str(self.layers[layer])
        mess += "\n"
        return mess
    
    def region_items(self):
        items = []
        for layer_name, layer in self.layers.items():
            full_key = self.key_stem if layer_name == "" else f"{self.key_stem}.{layer_name}"
            items.append((full_key, layer))
        return items

    def meta_items(self):
        """(path parts, value) pairs. Labels may contain dots, so paths are lists, never dotted strings."""
        stem = self.key_stem.split(".")
        items = []
        if self.layer_order and self.layer_order != ["auto"]:
            items.append((stem + ["_metadata", "z_order"], list(self.layer_order)))

        for kind, per_state in (("boxes", self.boxes), ("points", self.points)):
            for state, labels in per_state.items():
                state_path = stem + ([state] if state else [])
                for label, meta in labels.items():
                    wrapped = wrap_frames(meta.frames)
                    if wrapped is not None:
                        items.append((state_path + ["_metadata", kind, label], wrapped))

        return items
