"""Shared dimensions for the procedural street and building layout."""

CITY_CENTERS = {
    "A": (-40, 40),
    "B": (40, 40),
    "C": (-40, -40),
    "D": (40, -40),
}
ARTERIAL_CENTERS = (-60, -20, 20, 60)
ARTERIAL_WIDTH = 8.0
ARTERIAL_SIDEWALK_WIDTH = 1.8
ARTERIAL_SIDEWALK_OFFSET = 5.2
ARTERIAL_CURB_OFFSET = 4.15
LOCAL_WIDTH = 5.0
LOCAL_SIDEWALK_WIDTH = 1.0
LOCAL_SIDEWALK_OFFSET = 3.0
DISTRICT_SIZE = 38.0
LOT_LEVELS = (5.5, 8.7, 11.9)
MAX_BUILDING_FOOTPRINT = 2.6


def building_lots(count: int) -> list[tuple[float, float]]:
    """Return up to 36 evenly spaced plots around a clear cross street."""
    lot_cells = sorted(
        ((x, y) for x in LOT_LEVELS for y in LOT_LEVELS),
        key=lambda point: (point[0] ** 2 + point[1] ** 2, point),
    )
    quadrants = ((-1, -1), (1, -1), (-1, 1), (1, 1))
    per_quadrant, extra = divmod(min(count, 36), 4)
    positions = []
    for quadrant, (sign_x, sign_y) in enumerate(quadrants):
        lots_here = per_quadrant + (1 if quadrant < extra else 0)
        positions.extend(
            (sign_x * x, sign_y * y) for x, y in lot_cells[:lots_here]
        )
    return positions
