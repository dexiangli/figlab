"""UV–Vis spectra and conditional Tauc coordinates."""
from math import log, sinh

from .base import SpectrumProcessor, register


def tauc_coordinates(row):
    energy = 1239.841984 / float(row["wavelength_nm"])
    # Conditional on A = -log10(R); equivalent to (1-R)^2/(2R).
    km = 2 * sinh(log(10) * float(row["absorbance"]) / 2) ** 2
    return energy, (energy * km) ** 2


@register
class UVVisProcessor(SpectrumProcessor):
    name = "uvvis"

    def geometry(self, rows):
        return {"n_points": len(rows)}

    def truncate(self, rows, geom, tail):
        return rows
