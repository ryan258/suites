"""Local return-point backups. Release evidence and authority are never restored.

Only the versioned operator-editable fields can cross this boundary. A restore
requires the same canonical identities and locations, increments live revisions,
preserves saved target observations, and retains an undo backup before the commit.
"""
from __future__ import annotations

from copy import deepcopy
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import uuid

from . import catalog, registry
from .paths import CommitUnverified, install_new_file, open_confined_directory
from .txn import CommitUncertain, OccupantConflict, commit_replacement, write_temp_payload

VERSION = "portfolio-operator-backup-v1"
DIRECTORY = "operator-os/state/control-layer"
MAX_BYTES = 8_000_000
BACKUP_NAME = re.compile(r'[0-9]{8}T[0-9]{6}Z-[a-f0-9]{8}\.json')


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False, separators=(',', ':')).encode()


def _payload(doc):
    errors = catalog.validate_catalog(doc)
    if errors or 'catalog' not in doc:
        raise catalog.CatalogError('A valid reconciled catalog is required for a state backup.')
    return {r['name']: {'location': r['operator']['location'], 'owner': r['operator']['owner'],
                       'operator_schema': r['operator']['schema_version'],
                       'fields': {key: deepcopy(r['operator'][key]) for key in sorted(catalog.EDITABLE)}}
            for r in catalog.catalog_rows(doc)}


def make_backup(doc):
    payload = _payload(doc)
    return {'schema_version': VERSION, 'created_at': dt.datetime.now(dt.timezone.utc).isoformat(),
            'payload_sha256': hashlib.sha256(_canonical(payload)).hexdigest(), 'projects': payload}


def restore_document(doc, backup):
    if not isinstance(backup, dict) or set(backup) != {'schema_version', 'created_at', 'payload_sha256', 'projects'}:
        raise catalog.CatalogError('Backup fields are invalid.')
    if backup['schema_version'] != VERSION:
        raise catalog.CatalogError('Unsupported backup version; retain the original and use its matching reader.')
    payload = backup['projects']
    try:
        dt.datetime.fromisoformat(backup['created_at'])
        digest = hashlib.sha256(_canonical(payload)).hexdigest()
    except (ValueError, TypeError):
        raise catalog.CatalogError('Malformed backup metadata or payload.') from None
    if backup['payload_sha256'] != digest:
        raise catalog.CatalogError('Backup checksum mismatch; no state was changed.')
    current = _payload(doc)
    if not isinstance(payload, dict) or set(payload) != set(current):
        raise catalog.CatalogError('Project identities changed; automatic restore would lose or misassign work.')
    result = deepcopy(doc)
    changed = []
    for row in catalog.catalog_rows(result):
        name = row['name']; saved = payload[name]; live = current[name]
        if not isinstance(saved, dict) or set(saved) != set(live) or any(saved.get(k) != live[k] for k in ('location', 'owner', 'operator_schema')):
            raise catalog.CatalogError('Project ownership, location, or operator schema changed; reconcile before restoring.')
        fields = saved['fields']
        if not isinstance(fields, dict) or set(fields) != catalog.EDITABLE:
            raise catalog.CatalogError('Backup may contain only the complete set of operator-editable fields.')
        if fields != live['fields']:
            row['operator'].update(deepcopy(fields))
            row['operator']['revision'] += 1
            row['operator']['updated_at'] = dt.datetime.now(dt.timezone.utc).isoformat()
            row['operator']['update_source'] = 'explicit local state restore; not release approval'
            changed.append(name)
    errors = catalog.validate_catalog(result)
    if errors:
        raise catalog.CatalogError('Restored state is invalid: ' + '; '.join(errors))
    return result, changed


def _read(fd, name):
    file_fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    with os.fdopen(file_fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_BYTES:
            raise catalog.CatalogError('State must be a regular, unlinked file under 8 MB.')
        content = stream.read(MAX_BYTES + 1)
        if len(content) > MAX_BYTES:
            raise catalog.CatalogError('State file exceeds 8 MB.')
    return content, stat.S_IMODE(info.st_mode)


def _save(doc):
    name = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + uuid.uuid4().hex[:8] + '.json'
    fd = open_confined_directory(registry.SUITES_ROOT, DIRECTORY, create=True)
    try:
        install_new_file(fd, name, json.dumps(make_backup(doc), indent=2, allow_nan=False) + '\n')
    finally:
        os.close(fd)
    return name


def _load(name):
    if not isinstance(name, str) or (name != 'latest' and not BACKUP_NAME.fullmatch(name)):
        raise catalog.CatalogError('Use the backup filename printed by state backup.')
    fd = open_confined_directory(registry.SUITES_ROOT, DIRECTORY)
    try:
        if name == 'latest':
            candidates = []
            with os.scandir(fd) as entries:
                for index, entry in enumerate(entries):
                    if index >= 5000:
                        raise catalog.CatalogError('Too many backups to choose latest; use a specific filename.')
                    if BACKUP_NAME.fullmatch(entry.name):
                        info = entry.stat(follow_symlinks=False)
                        if stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                            candidates.append((info.st_mtime_ns, entry.name))
            if not candidates:
                raise catalog.CatalogError('No backup exists yet. Run ./s state backup first.')
            name = max(candidates)[1]
        content, _ = _read(fd, name)
        return name, json.loads(content)
    finally:
        os.close(fd)


def manage_state(action, name=None, apply=False):
    """Backup or preview/apply a restore using the existing ledger lock and CAS."""
    with registry._ledger_lock():
        directory_fd = open_confined_directory(registry.SUITES_ROOT, 'portfolio')
        try:
            before, mode = _read(directory_fd, 'project-ledger.json')
            doc = json.loads(before)
            if action == 'backup':
                return {'status': 'backed_up', 'backup': _save(doc)}
            if action != 'restore':
                raise catalog.CatalogError('Choose backup or restore.')
            name, backup = _load(name or 'latest')
            updated, changed = restore_document(doc, backup)
            result = {'status': 'preview', 'changed': changed, 'backup': name}
            if not apply or not changed:
                return result
            undo = _save(doc)
            result['undo_backup'] = undo
            temporary = write_temp_payload(directory_fd, 'project-ledger.json', catalog.render_ledger(updated), mode=mode)
            try:
                commit_replacement(directory_fd, 'project-ledger.json', temporary,
                                   expected_digest=hashlib.sha256(before).hexdigest())
            except OccupantConflict as error:
                raise catalog.CatalogConflict('Concurrent state was preserved; preview again. Undo backup: '+undo) from error
            except CommitUncertain as error:
                raise CommitUnverified('Restore committed but durability is unverified; inspect before retrying. Undo backup: '+undo) from error
            finally:
                temporary.close()
            result['status'] = 'restored'
            return result
        finally:
            os.close(directory_fd)
