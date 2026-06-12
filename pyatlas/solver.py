import math

import numpy as np

from pyatlas.parse_jsons import SpriteSheet
from pyatlas.core import log
from pyatlas.core.monitor import Chrono

chunk_size = 16
margin_factor = 1.35
max_growth_attempts = 12


class Box:
    def __init__(self, w, h, reference):
        self.w = w
        self.h = h
        self.ref = reference
        self.area = w * h

    def __lt__(self, other):
        return self.area < other.area


def adapt(sp_list: list[SpriteSheet]):
    ret = []

    for sp in sp_list:
        w = math.ceil(sp.total_width / chunk_size)
        h = math.ceil(sp.total_height / chunk_size)
        ret.append(Box(w, h, sp))

    return ret


def solve_placement(sp_list: list[SpriteSheet]):
    boxes = adapt(sp_list)
    if not boxes:
        return {
            "chunks_w": 1,
            "chunks_h": 1,
            "chunk_size": chunk_size,
            "margin": margin_factor,
        }

    total_area = sum(box.w * box.h for box in boxes)
    sum_width = sum(box.w for box in boxes)
    max_box_w = max((box.w for box in boxes), default=1)
    max_box_h = max((box.h for box in boxes), default=1)

    base_size = max(1, math.ceil(math.sqrt(total_area) * margin_factor))
    chunks_w = max(base_size, max_box_w)
    chunks_h = max(base_size, max_box_h)

    best_layout = None
    best_area = None

    with Chrono("solving placement :: initial growth phase"):
        for attempt in range(max_growth_attempts):
            placed, layout = try_place_boxes(boxes, chunks_w, chunks_h)
            if placed and layout is not None:
                best_layout = (chunks_w, chunks_h, layout)
                best_area = chunks_w * chunks_h
                break

            # Grow more smoothly than x2 to avoid very sparse first success bins.
            if attempt % 2 == 0:
                chunks_w = int(math.ceil(chunks_w * 1.5))
            else:
                chunks_h = int(math.ceil(chunks_h * 1.5))

    if best_layout is None:
        raise RuntimeError("unable to place all sprites in atlas after growth attempts")

    best_w, best_h, best_positions = best_layout

    with Chrono("solving placement :: optimization phase"):
        # Search smaller widths and minimal heights to find denser valid bins.
        for test_w in range(max_box_w, best_w + 1):
            min_h = max(max_box_h, math.ceil(total_area / test_w))
            max_h = best_area // test_w
            if min_h > max_h:
                continue

            for test_h in range(min_h, max_h + 1):
                placed, layout = try_place_boxes(boxes, test_w, test_h)
                if not placed or layout is None:
                    continue

                area = test_w * test_h
                if area < best_area or (area == best_area and test_h < best_h):
                    best_area = area
                    best_w = test_w
                    best_h = test_h
                    best_positions = layout
                break

    for box in boxes:
        box.ref.solver_pos = best_positions[id(box.ref)]

    return {
        "chunks_w": best_w,
        "chunks_h": best_h,
        "chunk_size": chunk_size,
        "margin": margin_factor,
    }


def try_place_boxes(boxes: list[Box], chunks_w: int, chunks_h: int):
    # Test multiple orderings; the first-fit order is often suboptimal for mixed row widths.
    orders = [
        sorted(boxes, key=lambda b: (b.h, b.w, b.area), reverse=True),
        sorted(boxes, key=lambda b: (b.w, b.h, b.area), reverse=True),
    ]

    best_positions = None
    best_fill_score = -1

    for ordered in orders:
        skyline = Skyline(chunks_w, chunks_h)
        positions = {}
        placed_all = True

        for box in ordered:
            pos = skyline.place_box(box)
            if pos is None:
                placed_all = False
                break
            positions[id(box.ref)] = pos

        if not placed_all:
            continue

        # Prefer layouts that push content upward and leftward.
        fill_score = 0
        for box in ordered:
            x, y = positions[id(box.ref)]
            fill_score += (chunks_h - y) * box.area

        if fill_score > best_fill_score:
            best_fill_score = fill_score
            best_positions = positions

    return (best_positions is not None), best_positions


class Skyline:
    """Skyline bin packing algorithm for efficient 2D rectangle placement.
    
    The skyline algorithm maintains a "skyline" - a list of horizontal segments 
    representing the top edge of already-placed boxes. Each segment stores its 
    x-position, y-height, and width.
    
    Algorithm:
    1. Start with one segment: the full bin width at height 0
    2. For each box to place:
       - Try each segment position
       - Calculate the required y-height (max height across spanned segments)
       - Choose position with minimal waste (lowest y, then leftmost x)
       - Update skyline by adding new segment for the placed box
       - Merge affected segments
    
    Complexity: O(n²) for n boxes in worst case, but typically O(n log n) with
    segment merging. Much faster than exhaustive O(WxHxn) grid search.
    
    Example skyline evolution:
        Initial:  |__________________|  y=0
        
        After placing 4x3 box at x=0:
                  |-------|           y=3
                  |__________________|  y=0
        
        After placing 2x5 box at x=4:
                  |-------|--|        y=5
                  |-------|           y=3
                  |__________________|  y=0
    
    Attributes:
        width: Maximum bin width in chunks
        height: Maximum bin height in chunks  
        segments: List of (x, y, width) tuples forming the skyline
    """
    
    def __init__(self, width: int, height: int):
        self.width = width
        self.height = height
        # Each segment is (x, y, width) representing a horizontal line at height y
        self.segments = [(0, 0, width)]
    
    def place_box(self, box: Box) -> tuple[int, int] | None:
        """Find the best position for a box using skyline algorithm."""
        best_x = None
        best_y = None
        best_idx = None
        best_waste = float('inf')
        
        # Try to place the box at each segment
        for i, (seg_x, seg_y, seg_w) in enumerate(self.segments):
            # Check if box can fit starting at this segment
            x = seg_x
            y = self._get_skyline_height(i, box.w)
            
            # Check bounds
            if x + box.w > self.width or y + box.h > self.height:
                continue
            
            # Calculate waste (prefer lower placement, then leftmost)
            waste = y * self.width + x
            
            if waste < best_waste:
                best_waste = waste
                best_x = x
                best_y = y
                best_idx = i
        
        if best_x is None:
            return None
        
        # Update skyline with the placed box
        self._merge_skyline(best_idx, best_x, best_y + box.h, box.w)
        
        return (best_x, best_y)
    
    def _get_skyline_height(self, start_idx: int, width: int) -> int:
        """Get the maximum height across segments that the box would span."""
        max_y = self.segments[start_idx][1]
        remaining_width = width
        x_start = self.segments[start_idx][0]
        
        for i in range(start_idx, len(self.segments)):
            seg_x, seg_y, seg_w = self.segments[i]
            
            # Check if this segment is contiguous
            if i > start_idx and seg_x > x_start + width:
                break
            
            max_y = max(max_y, seg_y)
            
            # Calculate how much of this segment we use
            overlap_start = max(seg_x, x_start)
            overlap_end = min(seg_x + seg_w, x_start + width)
            overlap_width = max(0, overlap_end - overlap_start)
            
            remaining_width -= overlap_width
            
            if remaining_width <= 0:
                break
        
        return max_y
    
    def _merge_skyline(self, start_idx: int, x: int, new_y: int, width: int):
        """Update skyline segments after placing a box."""
        new_segments = []
        
        # Keep segments before the placed box
        for i in range(start_idx):
            new_segments.append(self.segments[i])
        
        # Add new segment for the placed box
        new_segments.append((x, new_y, width))
        
        # Process segments that were affected by the placement
        i = start_idx
        while i < len(self.segments):
            seg_x, seg_y, seg_w = self.segments[i]
            
            # If segment is completely covered by the new box
            if seg_x >= x and seg_x + seg_w <= x + width:
                i += 1
                continue
            
            # If segment is to the right of the new box
            if seg_x >= x + width:
                new_segments.extend(self.segments[i:])
                break
            
            # If segment partially overlaps (left side sticks out)
            if seg_x < x:
                left_width = x - seg_x
                new_segments.append((seg_x, seg_y, left_width))
            
            # If segment partially overlaps (right side sticks out)
            if seg_x + seg_w > x + width:
                right_x = x + width
                right_width = (seg_x + seg_w) - right_x
                new_segments.append((right_x, seg_y, right_width))
            
            i += 1
        
        # Merge adjacent segments at the same height
        merged = []
        for seg in new_segments:
            if merged and merged[-1][1] == seg[1] and merged[-1][0] + merged[-1][2] == seg[0]:
                # Extend the previous segment
                last_x, last_y, last_w = merged[-1]
                merged[-1] = (last_x, last_y, last_w + seg[2])
            else:
                merged.append(seg)
        
        self.segments = merged


def contact_score(grid, chunks_w: int, chunks_h: int, x: int, y: int, w: int, h: int):
    score = 0

    if x == 0:
        score += h
    if y == 0:
        score += w
    if x + w == chunks_w:
        score += h
    if y + h == chunks_h:
        score += w

    if x > 0:
        score += int(np.sum(grid[x - 1, y : y + h]))
    if x + w < chunks_w:
        score += int(np.sum(grid[x + w, y : y + h]))
    if y > 0:
        score += int(np.sum(grid[x : x + w, y - 1]))
    if y + h < chunks_h:
        score += int(np.sum(grid[x : x + w, y + h]))

    return score


def place_single_box(grid, chunks_w: int, chunks_h: int, box: Box):
    max_x = chunks_w - box.w
    max_y = chunks_h - box.h
    if max_x < 0 or max_y < 0:
        return None

    best_x = None
    best_y = None
    best_score = -1

    for y in range(max_y + 1):
        for x in range(max_x + 1):
            if np.any(grid[x : x + box.w, y : y + box.h]):
                continue

            score = contact_score(grid, chunks_w, chunks_h, x, y, box.w, box.h)
            if (
                score > best_score
                or (score == best_score and (best_y is None or y < best_y))
                or (score == best_score and y == best_y and (best_x is None or x < best_x))
            ):
                best_score = score
                best_x = x
                best_y = y

    if best_x is None or best_y is None:
        return None

    grid[best_x : best_x + box.w, best_y : best_y + box.h] = 1
    return (int(best_x), int(best_y))
