from city3d.layout import (
    ARTERIAL_CENTERS,
    ARTERIAL_WIDTH,
    ARTERIAL_SIDEWALK_OFFSET,
    ARTERIAL_SIDEWALK_WIDTH,
    CITY_CENTERS,
    LOT_LEVELS,
    LOCAL_SIDEWALK_OFFSET,
    LOCAL_SIDEWALK_WIDTH,
    LOCAL_WIDTH,
    MAX_BUILDING_FOOTPRINT,
    building_lots,
)


def test_building_plots_clear_local_streets_and_sidewalks():
    half_building = MAX_BUILDING_FOOTPRINT * .98 / 2
    local_road_edge = LOCAL_WIDTH / 2
    local_sidewalk_outer_edge = LOCAL_SIDEWALK_OFFSET + LOCAL_SIDEWALK_WIDTH / 2

    assert min(abs(offset) - half_building for offset in LOT_LEVELS) > local_sidewalk_outer_edge
    assert local_sidewalk_outer_edge > local_road_edge
    assert LOCAL_SIDEWALK_OFFSET - LOCAL_SIDEWALK_WIDTH / 2 == local_road_edge


def test_building_plots_clear_arterials_and_outer_sidewalks():
    half_building = MAX_BUILDING_FOOTPRINT * .98 / 2
    sidewalk_outer_edge = ARTERIAL_SIDEWALK_OFFSET + ARTERIAL_SIDEWALK_WIDTH / 2
    assert ARTERIAL_SIDEWALK_OFFSET - ARTERIAL_SIDEWALK_WIDTH / 2 > ARTERIAL_WIDTH / 2

    for cx, cy in CITY_CENTERS.values():
        for x, y in building_lots(36):
            for coordinate, offset in ((cx, x), (cy, y)):
                for road in ARTERIAL_CENTERS:
                    if abs(road - coordinate) == 20:
                        nearest_edge = abs(road - (coordinate + offset)) - half_building
                        assert nearest_edge > sidewalk_outer_edge


def test_zone_building_counts_fit_non_overlapping_plot_grid():
    for count in (18, 22, 28, 36):
        plots = building_lots(count)
        assert len(plots) == count
        assert len(set(plots)) == count
        assert all(abs(x) >= LOT_LEVELS[0] and abs(y) >= LOT_LEVELS[0] for x, y in plots)
