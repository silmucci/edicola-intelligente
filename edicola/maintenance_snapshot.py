"""Preparazione locale dello snapshot, soltanto per PDF autorizzati uno per uno."""

from uuid import uuid4

from edicola.cloud import export_seed, validate_seed
from edicola.incremental import require_local_manager
from edicola.maintenance_store import maintenance_lock, private_directory


def prepare_snapshot(root, filenames, *, authorize_distribution=False):
    require_local_manager(root)
    if authorize_distribution is not True:
        raise PermissionError("Autorizzare la distribuzione dei PDF e dei dati derivati scelti.")
    with maintenance_lock(root):
        destination = private_directory(root) / ("snapshot-" + uuid4().hex[:12])
        export_seed(root, destination, filenames, authorize_distribution=True)
        manifest = validate_seed(destination)
        return destination, manifest
