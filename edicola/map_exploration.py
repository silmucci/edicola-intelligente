"""Focus dei soli nodi e archi già verificati; nessun retrieval."""


def focused_map(data, node_id):
    if not node_id or node_id not in {node["id"] for node in data["nodes"]}:
        return {"nodes": data["nodes"], "edges": data["edges"]}
    edges = [edge for edge in data["edges"] if node_id in (edge["from_id"], edge["to_id"])]
    neighbors = {node_id} | {endpoint for edge in edges for endpoint in (edge["from_id"], edge["to_id"])}
    nodes = [node for node in data["nodes"] if node["id"] in neighbors]
    if len(nodes) > 10:
        nodes.sort(key=lambda node: node["id"] != node_id)
    return {"nodes": nodes, "edges": edges}
