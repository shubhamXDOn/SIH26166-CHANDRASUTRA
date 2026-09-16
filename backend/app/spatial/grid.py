"""Deterministic spatial grid over normalized [0,1]² scene coordinates."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def _clamp_row(r: int, rows: int) -> int:
    if r < 0:
        return 0
    if r >= rows:
        return rows - 1
    return r


def _clamp_col(c: int, cols: int) -> int:
    if c < 0:
        return 0
    if c >= cols:
        return cols - 1
    return c


@dataclass(frozen=True)
class Grid:
    rows: int
    cols: int

    @property
    def total_cells(self) -> int:
        return self.rows * self.cols

    def cell_id(self, r: int, c: int) -> str:
        return f"R{r:02d}C{c:02d}"

    def rc(self, cell_id: str) -> tuple[int, int] | None:
        try:
            r, c = cell_id.strip().split("C", 1)
            return int(r[1:]), int(c)
        except (ValueError, IndexError):
            return None

    def to_cell(self, nx: float | np.ndarray, ny: float | np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Normalized coords → (row, col) arrays, clamped to the grid."""
        r = np.floor(np.asarray(ny, dtype=np.float64) * self.rows).astype(np.int64)
        c = np.floor(np.asarray(nx, dtype=np.float64) * self.cols).astype(np.int64)
        return _clamp_row_arr(r, self.rows), _clamp_col_arr(c, self.cols)

    def neighbors(self, r: int, c: int, radius: int = 1) -> list[tuple[int, int]]:
        out: list[tuple[int, int]] = []
        for dr in range(-radius, radius + 1):
            for dc in range(-radius, radius + 1):
                if dr == 0 and dc == 0:
                    continue
                nr, nc = r + dr, c + dc
                if 0 <= nr < self.rows and 0 <= nc < self.cols:
                    out.append((nr, nc))
        return out

    def cell_box(self, r: int, c: int) -> dict:
        return {
            "row_start": r / self.rows,
            "row_end": (r + 1) / self.rows,
            "col_start": c / self.cols,
            "col_end": (c + 1) / self.cols,
            "area_proxy": (1.0 / self.rows) * (1.0 / self.cols),
        }

    def all_cell_ids(self) -> list[str]:
        return [self.cell_id(r, c) for r in range(self.rows) for c in range(self.cols)]

    def is_edge_cell(self, r: int, c: int) -> bool:
        return r == 0 or r == self.rows - 1 or c == 0 or c == self.cols - 1


def _clamp_row_arr(r: np.ndarray, rows: int) -> np.ndarray:
    return np.clip(r, 0, rows - 1)


def _clamp_col_arr(c: np.ndarray, cols: int) -> np.ndarray:
    return np.clip(c, 0, cols - 1)