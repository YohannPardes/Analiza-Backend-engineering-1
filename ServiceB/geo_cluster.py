import math
from statistics import mean, median, quantiles

EARTH_RADIUS_KM = 6371.0


def haversine_km(lat1, lon1, lat2, lon2):
    """Great-circle distance between two points on Earth, in km."""
    lat1, lon1, lat2, lon2 = map(math.radians, (lat1, lon1, lat2, lon2))
    a = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def _distance(records, a, b):
    ra, rb = records[a], records[b]
    return haversine_km(ra["latitude"], ra["longitude"], rb["latitude"], rb["longitude"])


def _spanning_tree(records):
    """Minimum spanning tree (Prim's algorithm): list of (length_km, id_a, id_b) edges."""
    ids = list(records)
    if not ids:
        return []
    closest = {rid: (_distance(records, ids[0], rid), ids[0]) for rid in ids[1:]}   # id -> (distance, tree node)
    edges = []
    while closest:
        rid = min(closest, key=lambda r: closest[r][0])
        length, parent = closest.pop(rid)
        edges.append((length, parent, rid))
        for other, (best, _) in closest.items():
            d = _distance(records, rid, other)
            if d < best:
                closest[other] = (d, rid)
    return edges


def _cut_length(lengths):
    """Tukey's outlier fence (Q3 + 1.5 * IQR) over the tree's edge lengths."""
    lengths = [l for l in lengths if l > 0]     # identical coordinates carry no distance scale
    if len(lengths) < 2:
        return math.inf
    q1, _, q3 = quantiles(lengths, n=4, method="inclusive")
    return q3 + 1.5 * (q3 - q1)


def _neighbors(records):
    """Adjacency list of the spanning tree without its unusually long edges."""
    edges = _spanning_tree(records)
    cut = _cut_length([length for length, _, _ in edges])
    graph = {rid: [] for rid in records}
    for length, a, b in edges:
        if length <= cut:
            graph[a].append(b)
            graph[b].append(a)
    return graph


def _components(graph):
    """Connected components via iterative DFS."""
    seen, groups = set(), []
    for start in graph:
        if start in seen:
            continue
        stack, group = [start], []
        seen.add(start)
        while stack:
            node = stack.pop()
            group.append(node)
            for nxt in graph[node]:
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        groups.append(group)
    return groups


def cluster(records):
    """
    Zahn's MST clustering: link all points with a minimum spanning tree, drop the edges that
    are outliers among its lengths, and return the connected groups that remain.
    No distance parameter: the cut-off comes from the data itself.

    records: {record_id: {"latitude": .., "longitude": .., ...}}
    returns: {cluster_id: {median_coordinates, mean_coordinates, record_id: record, ...}}
    """
    records = {rid: r for rid, r in records.items()
               if r.get("latitude") is not None and r.get("longitude") is not None}

    result = {}
    for n, group in enumerate(_components(_neighbors(records)), start=1):
        lons = [records[rid]["longitude"] for rid in group]
        lats = [records[rid]["latitude"] for rid in group]
        entry = {
            "median_coordinates": [median(lons), median(lats)],
            "mean_coordinates": [mean(lons), mean(lats)],
        }
        for rid in group:
            entry[rid] = records[rid]
        result[f"cluster_{n}"] = entry
    return result



# if __name__ == "__main__":
#     # Example usage
#     example_records = {
#         "1": {"latitude": 40.7128, "longitude": -74.0060},  # New York
#         "2": {"latitude": 34.0522, "longitude": -118.2437},  # Los Angeles
#         "3": {"latitude": 41.8781, "longitude": -87.6298},  # Chicago
#         "4": {"latitude": 29.7604, "longitude": -95.3698},  # Houston
#         "5": {"latitude": 33.4484, "longitude": -112.0740},  # Phoenix
#     }
#     clusters = cluster(example_records)
#     print(clusters)
    