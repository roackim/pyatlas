import math

import numpy as np

from pyatlas.parse_jsons import SpriteSheet

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
    grid = np.zeros((chunks_w, chunks_h), dtype=np.uint8)

    # Test multiple orderings; the first-fit order is often suboptimal for mixed row widths.
    orders = [
        sorted(boxes, key=lambda b: (max(b.w, b.h), b.area), reverse=True),
        sorted(boxes, key=lambda b: (b.h, b.w, b.area), reverse=True),
        sorted(boxes, key=lambda b: (b.w, b.h, b.area), reverse=True),
    ]

    best_positions = None
    best_fill_score = -1

    for ordered in orders:
        grid.fill(0)
        positions = {}
        placed_all = True

        for box in ordered:
            pos = place_single_box(grid, chunks_w, chunks_h, box)
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
