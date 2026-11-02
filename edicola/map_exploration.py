"""Focus dei soli nodi e archi già verificati; nessun retrieval."""


def informative_nodes(data, limit):
    """Mantiene ponti documentati fra nodi pertinenti, entro lo stesso limite."""
    from collections import deque
    nodes = data["nodes"]
    if len(nodes) <= limit:
        return nodes
    neighbors = {n["id"]: [] for n in nodes}
    for edge in data["edges"]:
        if edge["kind"] == "documented":
            neighbors[edge["from_id"]].append(edge["to_id"])
            neighbors[edge["to_id"]].append(edge["from_id"])
    chosen = [nodes[0]["id"]]
    for node in nodes[1:limit]:
        queue = deque([[chosen[0]]])
        seen = {chosen[0]}
        path = []
        while queue:
            candidate = queue.popleft()
            if candidate[-1] == node["id"]:
                path = candidate
                break
            for other in neighbors[candidate[-1]]:
                if other not in seen:
                    seen.add(other)
                    queue.append(candidate + [other])
        additions = [identity for identity in path if identity not in chosen]
        if len(chosen) + len(additions) <= limit:
            chosen.extend(additions)
    for node in nodes:
        if len(chosen) < limit and node["id"] not in chosen:
            chosen.append(node["id"])
    return [node for node in nodes if node["id"] in chosen]


def focused_map(data, node_id):
    if not node_id or node_id not in {node["id"] for node in data["nodes"]}:
        return {"nodes": data["nodes"], "edges": data["edges"]}
    edges = [edge for edge in data["edges"] if node_id in (edge["from_id"], edge["to_id"])]
    neighbors = {node_id} | {endpoint for edge in edges for endpoint in (edge["from_id"], edge["to_id"])}
    nodes = [node for node in data["nodes"] if node["id"] in neighbors]
    if len(nodes) > 10:
        nodes.sort(key=lambda node: node["id"] != node_id)
    return {"nodes": nodes, "edges": edges}
