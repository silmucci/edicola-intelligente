"""Intervalli editoriali espliciti della domanda, mai date degli eventi."""
import re
from datetime import date
from edicola.timeline_dates import MONTHS


def scope_timeline(catalog, question):
    match = re.search(r"\bdal\s+(\d{1,2})\s+al\s+(\d{1,2})\s+(" + "|".join(MONTHS) + r")\s+(\d{4})\b", question, re.I)
    if not match:
        return catalog
    try:
        start, end = (date(int(match[4]), MONTHS[match[3].lower()], int(match[i])).isoformat() for i in (1, 2))
    except ValueError:
        raise ValueError("Intervallo delle edizioni non valido.") from None
    if start > end:
        raise ValueError("Intervallo delle edizioni non valido.")
    files = [f for f in catalog.coverage["files"] if start <= f.get("date", "") <= end]
    names = {f["pdf"] for f in files}
    chunks = [c for c in catalog.chunks if c.metadata["filename"] in names]
    return type(catalog)(chunks, {c.id: catalog.vectors[c.id] for c in chunks if c.id in catalog.vectors},
                         {**catalog.coverage, "files": files, "requested_editions": [start, end]})
