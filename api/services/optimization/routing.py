"""
api/services/optimization/routing.py
=============================================================================
ROUTE OPTIMIZER (the layer elevator_optimization.py is missing).

elevator_optimization.py decides WHO does WHAT (assignment). This module
decides the ORDER a single technician drives their assigned stops, so the
map polyline reflects the shortest real route.

  optimal_open_route(depot, stops, leg_dist_fn=None)
    - depot: (lat, lng) -> where the technician starts the day
    - stops: list of dicts, each with keys: id, lat, lng, is_aa (bool), payload
    - leg_dist_fn: OPTIONAL callable (stop_a, stop_b) -> km. When provided, it
      supplies the stop->stop leg distance (e.g. a Google-Maps-backed, cached
      distance, used to satisfy Req_33's "utilize distance/duration in route
      calculations"). When None, haversine is used -- DEFAULT, unchanged
      behaviour for every existing caller. Depot legs are ALWAYS haversine: the
      depot is the technician's moving GPS position, not a Unit, so the Google
      unit->unit cache does not apply to it.
    - returns: (ordered_stops, total_km)

Method: Gurobi open-path TSP (start at depot, visit every stop once, no
return). AA stops are FORCED before any non-AA stop (the 1-hour emergency
rule). If Gurobi is unavailable or fails, it falls back to an exact
brute-force for small routes / nearest-neighbour for large ones, so the
demo never breaks.
=============================================================================
"""
from math import radians, sin, cos, sqrt, atan2
from itertools import permutations


def haversine_km(lat1, lng1, lat2, lng2):
    R = 6371.0
    lat1, lng1, lat2, lng2 = map(radians, [float(lat1), float(lng1), float(lat2), float(lng2)])
    dlat = lat2 - lat1
    dlng = lng2 - lng1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlng / 2) ** 2
    return R * 2 * atan2(sqrt(a), sqrt(1 - a))


def _stop_to_stop_km(a, b, leg_dist_fn):
    """Stop->stop leg. Uses leg_dist_fn (e.g. Google) when provided, else
    haversine over the two stops' coordinates."""
    if leg_dist_fn is not None:
        return leg_dist_fn(a, b)
    return haversine_km(a["lat"], a["lng"], b["lat"], b["lng"])


def _depot_to_stop_km(depot, stop):
    """Depot leg is always haversine (moving GPS origin, not a Unit)."""
    return haversine_km(depot[0], depot[1], stop["lat"], stop["lng"])


def _path_length(depot, ordered, leg_dist_fn=None):
    total = 0.0
    prev = None
    for s in ordered:
        if prev is None:
            total += _depot_to_stop_km(depot, s)
        else:
            total += _stop_to_stop_km(prev, s, leg_dist_fn)
        prev = s
    return total


def _fallback_route(depot, stops, leg_dist_fn=None):
    """Exact for small n, nearest-neighbour for large. AA stays first."""
    aa = [s for s in stops if s.get("is_aa")]
    rest = [s for s in stops if not s.get("is_aa")]

    def seg_len(start_coord, segment):
        total = 0.0
        prev = None
        for s in segment:
            if prev is None:
                total += haversine_km(start_coord[0], start_coord[1], s["lat"], s["lng"])
            else:
                total += _stop_to_stop_km(prev, s, leg_dist_fn)
            prev = s
        return total

    def order_segment(start_coord, segment):
        if len(segment) <= 1:
            return list(segment)
        if len(segment) <= 8:
            best, best_d = None, None
            for perm in permutations(segment):
                d = seg_len(start_coord, list(perm))
                if best_d is None or d < best_d:
                    best, best_d = list(perm), d
            return best
        # nearest neighbour
        remaining = list(segment)
        out = []
        prev = None
        cur_coord = start_coord
        while remaining:
            if prev is None:
                nxt = min(remaining, key=lambda s: haversine_km(cur_coord[0], cur_coord[1], s["lat"], s["lng"]))
            else:
                nxt = min(remaining, key=lambda s: _stop_to_stop_km(prev, s, leg_dist_fn))
            out.append(nxt)
            remaining.remove(nxt)
            prev = nxt
        return out

    ordered_aa = order_segment(depot, aa)
    cursor = ((ordered_aa[-1]["lat"], ordered_aa[-1]["lng"]) if ordered_aa else depot)
    ordered_rest = order_segment(cursor, rest)
    ordered = ordered_aa + ordered_rest
    return ordered, _path_length(depot, ordered, leg_dist_fn)


def optimal_open_route(depot, stops, leg_dist_fn=None):
    """
    Returns (ordered_stops, total_km). Tries Gurobi first, falls back safely.

    leg_dist_fn(stop_a, stop_b) -> km optionally overrides the stop->stop leg
    distance (e.g. a Google-Maps-backed cached distance). When None, haversine
    is used -- the default, identical to the previous behaviour.
    """
    n = len(stops)
    if n == 0:
        return [], 0.0
    if n == 1:
        return list(stops), _path_length(depot, list(stops), leg_dist_fn)

    try:
        import gurobipy as gp
        from gurobipy import GRB
    except Exception:
        return _fallback_route(depot, stops, leg_dist_fn)

    try:
        # Nodes: 0 = depot, 1..n = stops
        coords = [depot] + [(s["lat"], s["lng"]) for s in stops]
        N = n + 1
        # arcs: from any node to any STOP (never back to depot 0)
        arcs = [(i, j) for i in range(N) for j in range(1, N) if i != j]

        dist = {}
        for (i, j) in arcs:
            if i == 0:
                dist[(i, j)] = _depot_to_stop_km(depot, stops[j - 1])
            else:
                dist[(i, j)] = _stop_to_stop_km(stops[i - 1], stops[j - 1], leg_dist_fn)

        m = gp.Model("open_route_tsp")
        m.setParam("OutputFlag", 0)
        m.setParam("TimeLimit", 10)

        a = m.addVars(arcs, vtype=GRB.BINARY, name="a")
        u = m.addVars(range(N), lb=0, ub=N - 1, vtype=GRB.CONTINUOUS, name="u")

        # depot leaves exactly once
        m.addConstr(gp.quicksum(a[0, j] for j in range(1, N)) == 1)
        # every stop entered exactly once
        for k in range(1, N):
            m.addConstr(gp.quicksum(a[i, k] for i in range(N) if i != k) == 1)
        # every stop leaves at most once (terminal stop leaves 0 times)
        for k in range(1, N):
            m.addConstr(gp.quicksum(a[k, j] for j in range(1, N) if j != k) <= 1)
        # exactly n arcs used (an open path over n+1 nodes)
        m.addConstr(gp.quicksum(a[i, j] for (i, j) in arcs) == n)

        # MTZ ordering / subtour elimination
        m.addConstr(u[0] == 0)
        for (i, j) in arcs:
            m.addConstr(u[j] >= u[i] + 1 - N * (1 - a[i, j]))

        # AA before non-AA (1-hour emergency rule)
        for ai, sa in enumerate(stops, start=1):
            for bi, sb in enumerate(stops, start=1):
                if sa.get("is_aa") and not sb.get("is_aa"):
                    m.addConstr(u[ai] <= u[bi] - 1)

        m.setObjective(gp.quicksum(dist[i, j] * a[i, j] for (i, j) in arcs), GRB.MINIMIZE)
        m.optimize()

        if m.Status not in (GRB.OPTIMAL, GRB.SUBOPTIMAL, GRB.TIME_LIMIT):
            return _fallback_route(depot, stops, leg_dist_fn)

        order = sorted(range(1, N), key=lambda k: u[k].X)
        ordered = [stops[k - 1] for k in order]
        return ordered, m.ObjVal

    except Exception:
        return _fallback_route(depot, stops, leg_dist_fn)
