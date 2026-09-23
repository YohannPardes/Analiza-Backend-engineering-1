import math
from statistics import mean, median

EARTH_RADIUS_KM = 6371.0


def haversine_km(lat1, lon1, lat2, lon2):
    """Great-circle distance between two points on Earth, in km."""
    lat1, lon1, lat2, lon2 = map(math.radians, (lat1, lon1, lat2, lon2))
    a = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def _neighbors(records, max_km):
    """Adjacency list: record id -> ids within max_km of it."""
    ids = list(records)
    graph = {rid: [] for rid in ids}
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            ra, rb = records[a], records[b]
            if haversine_km(ra["latitude"], ra["longitude"],
                            rb["latitude"], rb["longitude"]) <= max_km:
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


def cluster(records, max_km=200):
    """
    records: {record_id: {"latitude": .., "longitude": .., ...}}
    returns: {cluster_id: {median_coordinates, mean_coordinates, record_id: record, ...}}
    """
    records = {rid: r for rid, r in records.items()
               if r.get("latitude") is not None and r.get("longitude") is not None}

    result = {}
    for n, group in enumerate(_components(_neighbors(records, max_km)), start=1):
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
#     clusters = cluster(example_records, max_km=2000)
#     print(clusters)
    