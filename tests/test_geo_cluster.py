import pytest

from geo_cluster import _spanning_tree, cluster, haversine_km

PARIS = {"latitude": 48.8566, "longitude": 2.3522}
LONDON = {"latitude": 51.5074, "longitude": -0.1278}         # ~344 km from Paris
TOKYO = {"latitude": 35.6762, "longitude": 139.6503}

EUROPE = {
    "paris": PARIS,
    "versailles": {"latitude": 48.8049, "longitude": 2.1204},
    "brussels": {"latitude": 50.8503, "longitude": 4.3517},
    "amsterdam": {"latitude": 52.3676, "longitude": 4.9041},
    "london": LONDON,
}
JAPAN = {
    "tokyo": TOKYO,
    "yokohama": {"latitude": 35.4437, "longitude": 139.6380},
    "osaka": {"latitude": 34.6937, "longitude": 135.5023},
}


def groups(result):
    """Cluster contents as sets of record ids, ignoring the coordinate entries."""
    return sorted(({k for k in entry if not k.endswith("_coordinates")} for entry in result.values()),
                  key=sorted)


# --- haversine_km ---

def test_same_point_is_zero():
    assert haversine_km(48.8566, 2.3522, 48.8566, 2.3522) == 0


def test_paris_to_london():
    assert haversine_km(*PARIS.values(), *LONDON.values()) == pytest.approx(344, abs=2)


def test_distance_is_symmetric():
    assert haversine_km(*PARIS.values(), *TOKYO.values()) == pytest.approx(
        haversine_km(*TOKYO.values(), *PARIS.values()))


# --- _spanning_tree ---

def test_spanning_tree_links_every_point_once():
    edges = _spanning_tree({**EUROPE, **JAPAN})
    assert len(edges) == len(EUROPE) + len(JAPAN) - 1
    assert sum(length > 5000 for length, _, _ in edges) == 1      # a single Europe-Japan link


def test_spanning_tree_of_nothing():
    assert _spanning_tree({}) == []


# --- cluster ---

def test_continents_are_separated():
    assert groups(cluster({**EUROPE, **JAPAN})) == [set(EUROPE), set(JAPAN)]


def test_no_distance_parameter_is_needed_at_city_scale():
    # the same shape shrunk 100x: the cut-off scales with the data
    def shrink(points):
        return {k: {"latitude": p["latitude"] / 100, "longitude": p["longitude"] / 100}
                for k, p in points.items()}
    assert groups(cluster({**shrink(EUROPE), **shrink(JAPAN)})) == [set(EUROPE), set(JAPAN)]


def test_identical_coordinates_stay_together():
    same_city = {f"ip{i}": dict(PARIS) for i in range(6)}
    same_city["nearby"] = {"latitude": 48.8600, "longitude": 2.3600}
    assert len(cluster(same_city)) == 1


def test_too_few_points_form_a_single_cluster():
    assert len(cluster({"paris": PARIS, "tokyo": TOKYO})) == 1


def test_records_without_coordinates_are_skipped():
    result = cluster({"paris": PARIS, "unknown": {"latitude": None, "longitude": 1.0}})
    assert groups(result) == [{"paris"}]


def test_empty_input():
    assert cluster({}) == {}


def test_coordinates_are_lon_lat():
    entry = cluster({"paris": PARIS})["cluster_1"]
    assert entry["mean_coordinates"] == [2.3522, 48.8566]
    assert entry["median_coordinates"] == [2.3522, 48.8566]
    assert entry["paris"] == PARIS
