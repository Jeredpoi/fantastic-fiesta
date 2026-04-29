from __future__ import annotations

from pathlib import Path
from typing import Iterable

from geometry import Segment


def save_dxf(file_path: Path, segments: Iterable[Segment]) -> Path:
    file_path.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = [
        "0",
        "SECTION",
        "2",
        "HEADER",
        "9",
        "$ACADVER",
        "1",
        "AC1009",
        "9",
        "$INSUNITS",
        "70",
        "4",
        "0",
        "ENDSEC",
        "0",
        "SECTION",
        "2",
        "ENTITIES",
    ]

    for seg in segments:
        lines.extend(
            [
                "0",
                "LINE",
                "8",
                "CUT",
                "10",
                f"{seg.x1:.6f}",
                "20",
                f"{seg.y1:.6f}",
                "30",
                "0.0",
                "11",
                f"{seg.x2:.6f}",
                "21",
                f"{seg.y2:.6f}",
                "31",
                "0.0",
            ]
        )

    lines.extend(
        [
            "0",
            "ENDSEC",
            "0",
            "EOF",
        ]
    )

    file_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return file_path

