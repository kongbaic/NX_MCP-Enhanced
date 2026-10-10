from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

ProfilePlane = Literal["XY", "XZ", "YZ"]
ProfileTopology = Literal["L"]
ProfileSide = Literal["min", "max"]
ProfileCoordinateMode = Literal["overall_min", "centered_u_bottom_v"]


class MetricProfileSolveError(ValueError):
    """Engineering constraints do not define a valid deterministic profile."""


class MetricProfileSpec(BaseModel):
    """Metric-only closed-profile constraints.

    The solver deliberately accepts engineering values only. Raster coordinates
    and OCR geometry never enter this contract.
    """

    plane: ProfilePlane
    topology: ProfileTopology = "L"
    overall_u: float = Field(gt=0)
    overall_v: float = Field(gt=0)
    upright_width: float = Field(gt=0)
    base_height: float = Field(gt=0)
    upright_side: ProfileSide
    base_side: ProfileSide = "min"
    coordinate_mode: ProfileCoordinateMode = "overall_min"
    source_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _geometry_is_valid(self) -> "MetricProfileSpec":
        if self.upright_width >= self.overall_u:
            raise ValueError("upright_width must be smaller than overall_u")
        if self.base_height >= self.overall_v:
            raise ValueError("base_height must be smaller than overall_v")
        return self


class MetricProfileSolution(BaseModel):
    plane: ProfilePlane
    topology: ProfileTopology
    coordinate_mode: ProfileCoordinateMode
    vertices: list[dict[str, float]]
    segments: list[dict[str, float | str]]
    engineering_coordinate_inferred_from_pixels: bool = False


def _plane_axes(plane: ProfilePlane) -> tuple[str, str]:
    return {
        "XY": ("x", "y"),
        "XZ": ("x", "z"),
        "YZ": ("y", "z"),
    }[plane]


def _l_vertices(spec: MetricProfileSpec) -> list[tuple[float, float]]:
    u = float(spec.overall_u)
    v = float(spec.overall_v)
    w = float(spec.upright_width)
    h = float(spec.base_height)

    if spec.base_side == "min" and spec.upright_side == "max":
        points = [
            (0.0, 0.0),
            (u, 0.0),
            (u, v),
            (u - w, v),
            (u - w, h),
            (0.0, h),
        ]
    elif spec.base_side == "min" and spec.upright_side == "min":
        points = [
            (0.0, 0.0),
            (u, 0.0),
            (u, h),
            (w, h),
            (w, v),
            (0.0, v),
        ]
    elif spec.base_side == "max" and spec.upright_side == "max":
        points = [
            (0.0, v),
            (u, v),
            (u, 0.0),
            (u - w, 0.0),
            (u - w, v - h),
            (0.0, v - h),
        ]
    else:
        points = [
            (0.0, v),
            (u, v),
            (u, v - h),
            (w, v - h),
            (w, 0.0),
            (0.0, 0.0),
        ]

    if spec.coordinate_mode == "centered_u_bottom_v":
        shift = u / 2.0
        points = [(point_u - shift, point_v) for point_u, point_v in points]
    return points


def solve_metric_profile(spec: MetricProfileSpec) -> MetricProfileSolution:
    """Solve one closed profile from engineering constraints only."""

    if spec.topology != "L":
        raise MetricProfileSolveError(f"unsupported topology: {spec.topology!r}")

    axis_u, axis_v = _plane_axes(spec.plane)
    raw_vertices = _l_vertices(spec)
    vertices = [
        {axis_u: round(u, 12), axis_v: round(v, 12)}
        for u, v in raw_vertices
    ]

    segments: list[dict[str, float | str]] = []
    for index, start in enumerate(vertices):
        end = vertices[(index + 1) % len(vertices)]
        segments.append(
            {
                "type": "line",
                f"{axis_u}1": float(start[axis_u]),
                f"{axis_v}1": float(start[axis_v]),
                f"{axis_u}2": float(end[axis_u]),
                f"{axis_v}2": float(end[axis_v]),
            }
        )

    return MetricProfileSolution(
        plane=spec.plane,
        topology=spec.topology,
        coordinate_mode=spec.coordinate_mode,
        vertices=vertices,
        segments=segments,
        engineering_coordinate_inferred_from_pixels=False,
    )
