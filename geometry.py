from __future__ import annotations

from dataclasses import dataclass
import math
from typing import List, Tuple

Point = Tuple[float, float]
EdgeMode = bool | str | None
SHORT_OUT = "short_out"
SHORT_IN = "short_in"
ALT_OUT = "out_alt"
ALT_IN = "in_alt"


@dataclass(frozen=True)
class Segment:
    x1: float
    y1: float
    x2: float
    y2: float
    kind: str = "cut"  # "cut" | "slot"


@dataclass(frozen=True)
class Panel:
    name: str
    x: float
    y: float
    width: float
    height: float
    top: EdgeMode
    right: EdgeMode
    bottom: EdgeMode
    left: EdgeMode


@dataclass(frozen=True)
class Slot:
    name: str
    center_x: float
    center_y: float
    width: float
    height: float


@dataclass(frozen=True)
class LayoutResult:
    segments: List[Segment]
    panels: List[Panel]
    slots: List[Slot]
    total_width: float
    total_height: float


def _round(v: float) -> float:
    # Keep full geometry precision during construction.
    # Final DXF writing already formats values with 6 decimals.
    return float(v)


def _finger_count(length: float, thickness: float, spacing: float) -> int:
    # Match Jerome slider behavior (spacing is not a physical notch width).
    # JS reference:
    #   num = 0.6 * len / (2.5 * t)
    #   num = pow(num, 1 / (1 + spacing/50))
    #   segments = 2*floor(num) + 1
    base = 0.6 * length / (2.5 * thickness)
    base = max(base, 1.0)
    shaped = base ** (1.0 / (1.0 + spacing / 50.0))
    n = 2 * int(shaped // 1) + 1
    return max(3, n)


def _edge_outward(mode: EdgeMode) -> bool:
    return mode is True or mode in {SHORT_OUT, ALT_OUT}


def _edge_is_short(mode: EdgeMode) -> bool:
    return mode in {SHORT_OUT, SHORT_IN}


def _edge_phase(mode: EdgeMode) -> int:
    # Phase 1 starts with a straight segment (Jerome default).
    # Phase 0 starts with a tooth/slot, so a mating edge lands in the gaps.
    return 0 if mode in {ALT_OUT, ALT_IN} else 1


def _dovetail_edge_points(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    spacing: float,
    thickness: float,
    outward: bool,
    trim: float = 0.0,
    short: bool = False,
    phase: int = 1,
) -> List[Point]:
    """Finger/dovetail edge with explicit A/B phase for mating parts."""
    dx = x2 - x1
    dy = y2 - y1
    length = math.hypot(dx, dy)
    if length <= 0.001:
        return []

    ux = dx / length
    uy = dy / length
    n = _finger_count(length, thickness, spacing)
    step_x = dx / n
    step_y = dy / n

    normal_x = uy * thickness
    normal_y = -ux * thickness
    if not outward:
        normal_x = -normal_x
        normal_y = -normal_y

    px = x1
    py = y1
    raw: List[Point] = [(_round(px), _round(py))]
    for i in range(n):
        next_x = x1 + step_x * (i + 1)
        next_y = y1 + step_y * (i + 1)
        if i % 2 == phase:
            raw.extend(
                [
                    (_round(px + normal_x), _round(py + normal_y)),
                    (_round(next_x + normal_x), _round(next_y + normal_y)),
                    (_round(next_x), _round(next_y)),
                ]
            )
        else:
            raw.append((_round(next_x), _round(next_y)))
        px = next_x
        py = next_y

    inset = max(trim, thickness if short else 0.0)
    inset = max(0.0, min(inset, max(0.0, length / 2.0 - 0.001)))
    if inset <= 0.0:
        return raw[1:]

    raw[0] = (_round(x1 + ux * inset), _round(y1 + uy * inset))
    raw[-1] = (_round(x2 - ux * inset), _round(y2 - uy * inset))
    raw.append((_round(x2), _round(y2)))
    return raw


def _h_edge_lr(
    x: float,
    y: float,
    length: float,
    spacing: float,
    thickness: float,
    outward: bool,
    trim: float = 0.0,
    short: bool = False,
    phase: int = 1,
) -> List[Point]:
    return _dovetail_edge_points(
        x,
        y,
        x + length,
        y,
        spacing,
        thickness,
        outward,
        trim=trim,
        short=short,
        phase=phase,
    )


def _h_edge_rl(
    x: float,
    y: float,
    length: float,
    spacing: float,
    thickness: float,
    outward: bool,
    trim: float = 0.0,
    short: bool = False,
    phase: int = 1,
) -> List[Point]:
    return _dovetail_edge_points(
        x,
        y,
        x - length,
        y,
        spacing,
        thickness,
        outward,
        trim=trim,
        short=short,
        phase=phase,
    )


def _v_edge_td(
    x: float,
    y: float,
    length: float,
    spacing: float,
    thickness: float,
    outward: bool,
    trim: float = 0.0,
    short: bool = False,
    phase: int = 1,
) -> List[Point]:
    return _dovetail_edge_points(
        x,
        y,
        x,
        y + length,
        spacing,
        thickness,
        outward,
        trim=trim,
        short=short,
        phase=phase,
    )


def _v_edge_bu(
    x: float,
    y: float,
    length: float,
    spacing: float,
    thickness: float,
    outward: bool,
    trim: float = 0.0,
    short: bool = False,
    phase: int = 1,
) -> List[Point]:
    return _dovetail_edge_points(
        x,
        y,
        x,
        y - length,
        spacing,
        thickness,
        outward,
        trim=trim,
        short=short,
        phase=phase,
    )


def _panel_points(panel: Panel, spacing: float, thickness: float) -> List[Point]:
    x = panel.x
    y = panel.y
    w = panel.width
    h = panel.height

    points: List[Point] = [(_round(x), _round(y))]
    # Jerome-style edges already start with a straight segment, so we do not
    # manually trim the vertical sides. Short edges opt in per panel.
    trim_h = 0.0
    trim_v = 0.0

    # top →
    if panel.top is None:
        points.append((_round(x + w), _round(y)))
    else:
        points.extend(
            _h_edge_lr(
                x,
                y,
                w,
                spacing,
                thickness,
                _edge_outward(panel.top),
                trim=trim_h,
                short=_edge_is_short(panel.top),
                phase=_edge_phase(panel.top),
            )
        )

    # right ↓
    if panel.right is None:
        points.append((_round(x + w), _round(y + h)))
    else:
        points.extend(
            _v_edge_td(
                x + w,
                y,
                h,
                spacing,
                thickness,
                _edge_outward(panel.right),
                trim=trim_v,
                short=_edge_is_short(panel.right),
                phase=_edge_phase(panel.right),
            )
        )

    # bottom ←
    if panel.bottom is None:
        points.append((_round(x), _round(y + h)))
    else:
        points.extend(
            _h_edge_rl(
                x + w,
                y + h,
                w,
                spacing,
                thickness,
                _edge_outward(panel.bottom),
                trim=trim_h,
                short=_edge_is_short(panel.bottom),
                phase=_edge_phase(panel.bottom),
            )
        )

    # left ↑
    if panel.left is None:
        points.append((_round(x), _round(y)))
    else:
        points.extend(
            _v_edge_bu(
                x,
                y + h,
                h,
                spacing,
                thickness,
                _edge_outward(panel.left),
                trim=trim_v,
                short=_edge_is_short(panel.left),
                phase=_edge_phase(panel.left),
            )
        )

    # Explicitly close shape.
    if points[-1] != points[0]:
        points.append(points[0])
    return points


def _segments_from_points(points: List[Point], kind: str = "cut") -> List[Segment]:
    segments: List[Segment] = []
    for i in range(len(points) - 1):
        ax, ay = points[i]
        bx, by = points[i + 1]
        segments.append(Segment(ax, ay, bx, by, kind=kind))
    return segments


def _divider_tab_count(width: float, notch: float) -> int:
    # Close to Jerome "shelf holes" density: fewer tabs than main walls.
    count = int(round(width / max(1.0, notch * 2.0)))
    return max(1, min(9, count))


def _divider_tab_width(width: float, notch: float, thickness: float) -> float:
    count = _divider_tab_count(width, notch)
    step = width / (count + 1)
    return max(thickness * 1.8, min(notch * 0.45, step * 0.7))


def _divider_tab_centers(x: float, width: float, notch: float) -> List[float]:
    count = _divider_tab_count(width, notch)
    return [x + (i + 1) * width / (count + 1) for i in range(count)]


def _divider_points(
    panel: Panel,
    thickness: float,
    notch: float,
    side_tab_len: float,
    add_top_tab: bool,
) -> List[Point]:
    """
    Divider profile with one center tab on each side wall joint and one center
    bottom tab for the base slot. In closed mode it also gets a top tab for lid.
    """
    x = panel.x
    y = panel.y
    w = panel.width
    h = panel.height

    # Side tabs should be vertical, matching divider orientation.
    tab_h = min(max(thickness, side_tab_len), max(thickness, h - 2.0))
    side_tab_depth = thickness
    tab_w = _divider_tab_width(w, notch, thickness)
    top_bottom_centers = _divider_tab_centers(x, w, notch)

    y1 = y + (h - tab_h) / 2.0
    y2 = y1 + tab_h

    points: List[Point] = [(_round(x), _round(y))]

    # top →
    if add_top_tab:
        cursor = x
        for c in top_bottom_centers:
            lx = max(x, c - tab_w / 2.0)
            rx = min(x + w, c + tab_w / 2.0)
            if lx > cursor:
                points.append((_round(lx), _round(y)))
            points.extend(
                [
                    (_round(lx), _round(y - thickness)),
                    (_round(rx), _round(y - thickness)),
                    (_round(rx), _round(y)),
                ]
            )
            cursor = rx
        if cursor < x + w:
            points.append((_round(x + w), _round(y)))
    else:
        points.append((_round(x + w), _round(y)))

    # right ↓ (center tab, vertical)
    points.extend(
        [
            (_round(x + w), _round(y1)),
            (_round(x + w + side_tab_depth), _round(y1)),
            (_round(x + w + side_tab_depth), _round(y2)),
            (_round(x + w), _round(y2)),
            (_round(x + w), _round(y + h)),
        ]
    )

    # bottom ← (multiple tabs to match base slots)
    bottom_y = y + h
    cursor = x + w
    for c in reversed(top_bottom_centers):
        lx = max(x, c - tab_w / 2.0)
        rx = min(x + w, c + tab_w / 2.0)
        if cursor > rx:
            points.append((_round(rx), _round(bottom_y)))
        points.extend(
            [
                (_round(rx), _round(bottom_y + thickness)),
                (_round(lx), _round(bottom_y + thickness)),
                (_round(lx), _round(bottom_y)),
            ]
        )
        cursor = lx
    if cursor > x:
        points.append((_round(x), _round(bottom_y)))

    # left ↑ (center tab, vertical)
    points.extend(
        [
            (_round(x), _round(y2)),
            (_round(x - side_tab_depth), _round(y2)),
            (_round(x - side_tab_depth), _round(y1)),
            (_round(x), _round(y1)),
            (_round(x), _round(y)),
        ]
    )

    if points[-1] != points[0]:
        points.append(points[0])
    return points


def _slot_segments(slot: Slot) -> List[Segment]:
    x1 = slot.center_x - slot.width / 2
    y1 = slot.center_y - slot.height / 2
    x2 = x1 + slot.width
    y2 = y1 + slot.height
    points = [
        (_round(x1), _round(y1)),
        (_round(x2), _round(y1)),
        (_round(x2), _round(y2)),
        (_round(x1), _round(y2)),
        (_round(x1), _round(y1)),
    ]
    return _segments_from_points(points, kind="slot")


def _sloped_side_panel_points(
    panel: Panel,
    spacing: float,
    thickness: float,
    slope: float,
    side: str,
    dovetail_on_slope: bool,
) -> List[Point]:
    x = panel.x
    y = panel.y
    w = panel.width
    h = panel.height
    # Respect the entered slope amount; only clamp to geometry-safe max.
    s = max(0.0, min(slope, max(0.0, h - thickness)))
    trim_h = 0.0
    trim_v = 0.0

    n = max(3, _finger_count(max(w, thickness), thickness, spacing))
    dx = w / n
    dy = s / n if n > 0 else 0.0

    if side == "left":
        points: List[Point] = [(_round(x), _round(y - s))]
        if dovetail_on_slope:
            cx = x
            cy = y - s
            # Closed mode: staircase on sloped top edge.
            for _ in range(n):
                cx += dx
                points.append((_round(cx), _round(cy)))
                cy += dy
                points.append((_round(cx), _round(cy)))
        else:
            # Open mode: straight sloped top edge like reference.
            points.append((_round(x + w), _round(y)))
        if panel.right is None:
            points.append((_round(x + w), _round(y + h)))
        else:
            points.extend(
                _v_edge_td(
                    x + w,
                    y,
                    h,
                    spacing,
                    thickness,
                    _edge_outward(panel.right),
                    trim=trim_v,
                    short=_edge_is_short(panel.right),
                    phase=_edge_phase(panel.right),
                )
            )
        if panel.bottom is None:
            points.append((_round(x), _round(y + h)))
        else:
            points.extend(
                _h_edge_rl(
                    x + w,
                    y + h,
                    w,
                    spacing,
                    thickness,
                    _edge_outward(panel.bottom),
                    trim=trim_h,
                    short=_edge_is_short(panel.bottom),
                    phase=_edge_phase(panel.bottom),
                )
            )
        points.append((_round(x), _round(y - s)))
    else:
        points = [(_round(x + w), _round(y - s))]
        if dovetail_on_slope:
            cx = x + w
            cy = y - s
            # Closed mode: mirrored staircase.
            for _ in range(n):
                cx -= dx
                points.append((_round(cx), _round(cy)))
                cy += dy
                points.append((_round(cx), _round(cy)))
        else:
            # Open mode: straight sloped top edge.
            points.append((_round(x), _round(y)))
        if panel.left is None:
            points.append((_round(x), _round(y + h)))
        else:
            points.extend(
                _v_edge_td(
                    x,
                    y,
                    h,
                    spacing,
                    thickness,
                    _edge_outward(panel.left),
                    trim=trim_v,
                    short=_edge_is_short(panel.left),
                    phase=_edge_phase(panel.left),
                )
            )
        if panel.bottom is None:
            points.append((_round(x + w), _round(y + h)))
        else:
            points.extend(
                _h_edge_lr(
                    x,
                    y + h,
                    w,
                    spacing,
                    thickness,
                    _edge_outward(panel.bottom),
                    trim=trim_h,
                    short=_edge_is_short(panel.bottom),
                    phase=_edge_phase(panel.bottom),
                )
            )
        points.append((_round(x + w), _round(y - s)))

    if points[-1] != points[0]:
        points.append(points[0])
    return points


def _make_panels_and_slots(
    width_x: float,
    length_y: float,
    height_z: float,
    notch: float,
    thickness: float,
    box_type: str,
    show_dividers: bool,
    divider_count: int,
) -> tuple[List[Panel], List[Slot], float, float]:
    pad = 10.0
    # Keep panel layout size independent from spacing slider.
    # Spacing controls tooth density only, not sheet footprint.
    gap = thickness + 5.0
    # Y is the full external run length in the reference layout.
    run_len = length_y

    side_w = height_z
    side_h = run_len  # sides are dominant panels, full external size

    bottom_x = pad + side_w + gap
    bottom_y = pad + height_z + gap

    back_x = bottom_x
    back_y = pad
    front_x = bottom_x
    front_y = bottom_y + run_len + gap

    left_x = pad
    left_y = bottom_y
    right_x = bottom_x + width_x + gap
    right_y = bottom_y

    panel_bottom_name = "Дно"
    if box_type == "frame":
        panel_bottom_name = "Рамка"

    # Jerome layout logic:
    # - Side panels (Left/Right) are full external height (run_len), teeth outward on top/bottom
    # - Back/Front panels fit BETWEEN side panels: width=width_x, height=height_z
    #   their left/right edges go inward (ALT_IN) to mate with side panel teeth
    # - Bottom panel fits between sides: teeth inward on left/right (ALT_IN),
    #   teeth outward on top/bottom (SHORT_OUT) to mate with back/front

    panels: List[Panel] = [
        # Bottom panel: slots into all 4 walls, teeth inward everywhere
        Panel(panel_bottom_name, bottom_x, bottom_y, width_x, run_len,
              ALT_IN,   # top: inward, slots into back wall
              ALT_IN,   # right: inward, slots into right wall
              ALT_IN,   # bottom: inward, slots into front wall
              ALT_IN),  # left: inward, slots into left wall
        # Back wall: fits between left/right side panels, no teeth on sides
        Panel(
            "Задняя",
            back_x,
            back_y,
            width_x,
            height_z,
            None if box_type == "open" else True,  # top: open or lid
            None,   # right: no teeth, side panel covers this edge
            True,   # bottom: outward, mates bottom panel top (ALT_IN)
            None,   # left: no teeth, side panel covers this edge
        ),
        # Front wall: fits between left/right side panels
        Panel(
            "Передняя",
            front_x,
            front_y,
            width_x,
            height_z,
            True,   # top: outward, mates bottom panel bottom (ALT_IN)
            None,   # right: no teeth, side panel covers this edge
            None if box_type == "open" else True,  # bottom: open or lid
            None,   # left: no teeth, side panel covers this edge
        ),
        # Left wall: dominant panel, full external Y size
        Panel(
            "Левая",
            left_x,
            left_y,
            side_w,
            side_h,
            True,   # top: outward teeth, mates back wall left edge
            ALT_IN, # right: inward, mates bottom left edge
            True,   # bottom: outward teeth, mates front wall left edge
            None if box_type == "open" else True,
        ),
        # Right wall: dominant panel, full external Y size
        Panel(
            "Правая",
            right_x,
            right_y,
            side_w,
            side_h,
            True,   # top: outward teeth, mates back wall right edge
            None if box_type == "open" else True,
            True,   # bottom: outward teeth, mates front wall right edge
            ALT_IN, # left: inward, mates bottom right edge
        ),
    ]

    lid_y: float | None = None
    if box_type == "closed":
        lid_x = bottom_x
        lid_y = front_y + height_z + gap
        # Lid is complementary to top rims of all walls, so use the response phase.
        panels.append(Panel("Крышка", lid_x, lid_y, width_x, run_len, ALT_IN, ALT_IN, ALT_IN, ALT_IN))

    total_w = right_x + side_w + pad
    total_h = front_y + height_z + pad
    if box_type == "closed":
        total_h = max(total_h, lid_y + run_len + pad)

    slots: List[Slot] = []
    if show_dividers and divider_count > 0 and box_type in {"open", "closed"}:
        divider_x = total_w + gap
        slot_len = min(max(thickness * 2.5, notch * 0.45), width_x / 6.0)
        slot_w = _divider_tab_width(width_x, notch, thickness)
        slot_centers_x = _divider_tab_centers(bottom_x, width_x, notch)
        # Divider profile has tabs on top and bottom, so keep extra vertical gap
        # between divider parts to avoid overlapping outlines in preview/export.
        divider_step = height_z + (2.0 * thickness) + gap * 0.7

        for idx in range(divider_count):
            divider_y = front_y + idx * divider_step
            panels.append(
                Panel(
                    f"Перегородка {idx + 1}",
                    divider_x,
                    divider_y,
                    width_x,
                    height_z,
                    None,
                    None,
                    None,
                    None,
                )
            )

            y_pos = bottom_y + (idx + 1) * (run_len / (divider_count + 1))
            # Bottom slots: pattern matches divider bottom tabs.
            for s_idx, cx in enumerate(slot_centers_x, start=1):
                slots.append(
                    Slot(
                        f"Слот-дно {idx + 1}.{s_idx}",
                        center_x=cx,
                        center_y=y_pos,
                        width=slot_w,
                        height=thickness,
                    )
                )
            # Side-wall slots: horizontal (left-right) per divider.
            slots.append(
                Slot(
                    f"Слот-левая {idx + 1}",
                    # Side-wall divider slots must be vertical cut-outs in the wall body.
                    center_x=left_x + side_w / 2.0,
                    center_y=y_pos,
                    width=slot_len,
                    height=thickness,
                )
            )
            slots.append(
                Slot(
                    f"Слот-правая {idx + 1}",
                    center_x=right_x + side_w / 2.0,
                    center_y=y_pos,
                    width=slot_len,
                    height=thickness,
                )
            )
            if box_type == "closed" and lid_y is not None:
                lid_y_pos = lid_y + (idx + 1) * (run_len / (divider_count + 1))
                for s_idx, cx in enumerate(slot_centers_x, start=1):
                    slots.append(
                        Slot(
                            f"Слот-крышка {idx + 1}.{s_idx}",
                            center_x=cx,
                            center_y=lid_y_pos,
                            width=slot_w,
                            height=thickness,
                        )
                    )

        total_w = divider_x + width_x + thickness + pad
        last_divider_y = front_y + (divider_count - 1) * divider_step
        total_h = max(total_h, last_divider_y + height_z + thickness + pad)

    if box_type == "frame":
        # Central cutout for frame mode.
        frame_w = max(thickness * 8.0, width_x - thickness * 6.0)
        frame_h = max(thickness * 8.0, run_len - thickness * 6.0)
        slots.append(
            Slot(
                "Окно-рамка",
                center_x=bottom_x + width_x / 2.0,
                center_y=bottom_y + run_len / 2.0,
                width=min(frame_w, width_x - thickness * 2.0),
                height=min(frame_h, run_len - thickness * 2.0),
            )
        )

    return panels, slots, _round(total_w), _round(total_h)


def generate_laser_layout(
    width_x: float,
    length_y: float,
    height_z: float,
    thickness: float,
    notch: float,
    box_type: str,
    show_dividers: bool,
    divider_count: int,
    sloped: bool = False,
    slope: float = 0.0,
) -> LayoutResult:
    valid_types = {"open", "closed", "frame"}
    if box_type not in valid_types:
        raise ValueError("box_type must be open, closed, or frame")

    values = {
        "width_x": width_x,
        "length_y": length_y,
        "height_z": height_z,
        "thickness": thickness,
        "notch": notch,
    }
    for name, value in values.items():
        if value <= 0:
            raise ValueError(f"{name} must be > 0")
    if divider_count < 0:
        raise ValueError("divider_count must be >= 0")
    if notch < thickness * 1.5:
        raise ValueError("notch must be at least 1.5 * thickness")
    if slope < 0:
        raise ValueError("slope must be >= 0")

    panels, slots, total_w, total_h = _make_panels_and_slots(
        width_x=width_x,
        length_y=length_y,
        height_z=height_z,
        notch=notch,
        thickness=thickness,
        box_type=box_type,
        show_dividers=show_dividers,
        divider_count=divider_count,
    )

    segments: List[Segment] = []
    divider_side_tab_len = min(max(thickness * 2.5, notch * 0.45), width_x / 6.0)
    for panel in panels:
        if panel.name.startswith("Перегородка") and box_type in {"open", "closed"}:
            points = _divider_points(
                panel,
                thickness=thickness,
                notch=notch,
                side_tab_len=divider_side_tab_len,
                add_top_tab=(box_type == "closed"),
            )
        elif sloped and panel.name == "Левая":
            points = _sloped_side_panel_points(
                panel,
                notch,
                thickness,
                slope,
                side="left",
                dovetail_on_slope=(box_type == "closed"),
            )
        elif sloped and panel.name == "Правая":
            points = _sloped_side_panel_points(
                panel,
                notch,
                thickness,
                slope,
                side="right",
                dovetail_on_slope=(box_type == "closed"),
            )
        else:
            points = _panel_points(panel, notch, thickness)
        segments.extend(_segments_from_points(points, kind="cut"))
    for slot in slots:
        segments.extend(_slot_segments(slot))

    return LayoutResult(
        segments=segments,
        panels=panels,
        slots=slots,
        total_width=total_w,
        total_height=total_h,
    )
