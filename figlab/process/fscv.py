"""FSCV points are plotted in acquisition order."""

from .base import SpectrumProcessor, register


@register
class FSCVProcessor(SpectrumProcessor):
    name = "fscv"

    def geometry(self, rows):
        return {"n_points": len(rows)}

    def truncate(self, rows, geom, tail):
        return sorted(rows, key=lambda row: float(row["point_index"]))
