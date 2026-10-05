"""Operator metadata on the existing project ledger, independent of release truth.

The original ``projects`` array retains migration-enrollment compatibility. New entries
live in ``catalog_additions`` in that same ledger, never in a second inventory. Both
arrays own identical operator records and are projected together here. Nested inventory
and app shortcuts refer to those identities; they do not own restart state.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from . import registry
from .paths import CommitUnverified, open_confined_directory
from .txn import CommitUncertain, OccupantConflict, commit_replacement, write_temp_payload

HOMES = {
    'operator-os': 'Home Base', 'accessibility': 'Accessibility',
    'brand-publishing': 'Voice & Publishing', 'production-house': 'Story & Audio',
    'model-behavior-lab': 'Model Lab', 'discovery-decision': 'Thinking & Discovery',
    'agent-reliability': 'Agent Workshop', 'game-design': 'Games & Worlds',
    'independent': 'Independent Projects',
}
ATTENTION = {'now': 'Now', 'in-use': 'In use', 'waiting': 'Waiting', 'parked': 'Parked', None: 'Unassigned'}
NOW_LIMIT = 3
EDITABLE = frozenset({'purpose', 'resume', 'attention', 'now_order', 'next_action', 'waiting_trigger', 'done_for_now', 'restart_note'})
TEXT_FIELDS = ('purpose', 'next_action', 'waiting_trigger', 'done_for_now', 'restart_note')


class CatalogError(ValueError):
    """Actionable invalid or incomplete operator data."""


class CatalogConflict(CatalogError):
    """Another session changed this record; reload before saving."""


def catalog_rows(ledger):
    return [*ledger.get('projects', []), *ledger.get('catalog_additions', [])]


def _date(value):
    try:
        dt.date.fromisoformat(value)
        return True
    except (ValueError, TypeError):
        return False


def _resume_errors(resume, location):
    if resume is None:
        return []
    if not isinstance(resume, dict):
        return ['resume must be an object or null']
    kind, target = resume.get('kind'), resume.get('target')
    if not isinstance(kind, str) or kind not in ('file', 'directory', 'url', 'command') or not isinstance(target, str) or not target.strip() or any(ord(c) < 32 for c in target):
        return ['resume needs a supported kind and a nonempty target']
    if not _date(resume.get('observed_at')):
        return ['resume observation date is invalid']
    if kind in ('file', 'directory'):
        try:
            p = Path(target)
            if not p.is_absolute() or not p.is_relative_to(Path(location)):
                return ['local resume target must be inside its owning project']
            if '..' in p.parts:
                return ['local resume target cannot traverse directories']
        except (TypeError, ValueError):
            return ['invalid local resume target']
        if kind == 'file' and (not isinstance(resume.get('sha256'), str) or not re.fullmatch('[a-f0-9]{64}', resume['sha256'])):
            return ['file resume target requires its observed sha256']
    if kind == 'url':
        try:
            u = urlsplit(target)
            valid = u.scheme in ('https', 'http') and u.hostname and not u.username and not u.password
            if u.scheme == 'http' and u.hostname not in ('localhost', '127.0.0.1', '::1'):
                valid = False
            u.port
        except ValueError:
            valid = False
        if not valid:
            return ['resume URL must be HTTPS or local HTTP, without credentials']
    if kind == 'command' and '\n' in target:
        return ['resume commands must be one line and are displayed only']
    return []


def validate_catalog(ledger):
    """Versioned extension validation; legacy ledgers remain readable."""
    if not isinstance(ledger, dict): return ['project ledger must be an object']
    if 'catalog' not in ledger:
        return []
    errors = []
    if not isinstance(ledger.get('projects'), list): return ['projects must be an array']
    meta = ledger['catalog']
    if not isinstance(meta, dict) or meta.get('schema_version') != '1.0.0' or meta.get('homes') != HOMES or meta.get('now_limit') != NOW_LIMIT:
        return ['catalog metadata, home IDs, or Now ceiling is invalid']
    if not isinstance(ledger.get('catalog_additions'), list):
        return ['catalog_additions must be an array']
    ids, locations, orders = set(), set(), []
    for row in catalog_rows(ledger):
        op = row.get('operator') if isinstance(row, dict) else None
        if not isinstance(op, dict):
            errors.append('catalog project requires an operator record'); continue
        name = row.get('name')
        prefix = f'{name}: '
        if not isinstance(name, str) or not name or op.get('id') != name or name in ids:
            errors.append(prefix + 'identity missing or duplicated')
        else:
            ids.add(name)
        if 'resume' not in op or 'now_order' not in op: errors.append(prefix + 'resume and order must be explicit, including null')
        if not isinstance(op.get('notes'), list) or any(not isinstance(note, str) for note in op['notes']): errors.append(prefix + 'notes must be a string array')
        if op.get('schema_version') != '1.0.0': errors.append(prefix + 'unsupported operator schema')
        location = op.get('location')
        if not isinstance(location, str) or not Path(location).is_absolute() or location in locations:
            errors.append(prefix + 'location must be a unique absolute path')
        else:
            locations.add(location)
        if not isinstance(op.get('primary_home'), str) or op['primary_home'] not in HOMES: errors.append(prefix + 'unknown home')
        related = op.get('related_suites')
        if not isinstance(related, list) or any(not isinstance(x, str) or x not in HOMES or x in ('independent', op.get('primary_home')) for x in related) or len(set(related)) != len(related):
            errors.append(prefix + 'related suites must be distinct supporting suite IDs')
        if op.get('inventory_kind') not in ('project', 'container', 'nested_repository'): errors.append(prefix + 'invalid inventory kind')
        if op.get('identity_status') not in ('observed', 'missing', 'unresolved'): errors.append(prefix + 'invalid identity status')
        if not isinstance(op.get('owner'), str) or not op['owner'].strip(): errors.append(prefix + 'owner is required')
        if not _date(op.get('observed_at')) or not isinstance(op.get('provenance'), list) or not op['provenance']:
            errors.append(prefix + 'observation and provenance are required')
        elif any(not isinstance(p, dict) or not isinstance(p.get('source'), str) or not p['source'].strip() or not _date(p.get('observed_at')) for p in op['provenance']):
            errors.append(prefix + 'each provenance item needs a source and date')
        revision = op.get('revision')
        if type(revision) is not int or revision < 0: errors.append(prefix + 'revision must be a nonnegative integer')
        for field in TEXT_FIELDS:
            value = op.get(field)
            if field not in op or value is not None and (not isinstance(value, str) or not value.strip() or len(value) > 8000):
                errors.append(prefix + field + ' must be text or explicit null')
        attention = op.get('attention')
        if 'attention' not in op or not (attention is None or isinstance(attention, str) and attention in ATTENTION):
            errors.append(prefix + 'invalid attention state')
        if attention == 'waiting' and not op.get('waiting_trigger'): errors.append(prefix + 'Waiting requires an observable trigger')
        if attention == 'now':
            order = op.get('now_order')
            if type(order) is not int or not 1 <= order <= NOW_LIMIT: errors.append(prefix + 'Now order must be 1–3')
            else: orders.append(order)
        elif op.get('now_order') is not None: errors.append(prefix + 'only Now may have an order')
        errors.extend(prefix + e for e in _resume_errors(op.get('resume'), location))
    if len(orders) > NOW_LIMIT or len(set(orders)) != len(orders): errors.append('Now is limited to three distinct ordered projects')
    if not isinstance(meta.get('app_entries'), list) or not isinstance(meta.get('unresolved'), list): return errors + ['app entries and unresolved identities must be arrays']
    for entry in meta.get('app_entries', []):
        if not isinstance(entry, dict):
            errors.append('app entry must be an object'); continue
        if entry.get('project') is not None and (not isinstance(entry['project'], str) or entry['project'] not in ids): errors.append('app entry refers to an unknown catalog identity')
    return errors


def load_catalog_ledger():
    doc = registry.load_ledger()
    if 'catalog' not in doc: raise CatalogError('No reconciled catalog is recorded yet.')
    errors = validate_catalog(doc)
    if errors: raise CatalogError('; '.join(errors))
    return doc


def resolve_project(query, ledger=None):
    doc = ledger if ledger is not None else load_catalog_ledger()
    if not isinstance(query, str) or not query.strip(): raise CatalogError('Name a project or a unique short prefix.')
    query = query.strip().casefold()
    rows = catalog_rows(doc)
    exact = [r for r in rows if r['name'].casefold() == query or r['operator']['location'].casefold() == query]
    aliases = {e['project'] for e in doc['catalog'].get('app_entries', []) if e.get('project') and e['label'].casefold() == query}
    matches = exact or [r for r in rows if r['name'] in aliases or Path(r['name']).name.casefold() == query]
    matches = matches or [r for r in rows if r['name'].casefold().startswith(query) or Path(r['name']).name.casefold().startswith(query)]
    if len(matches) != 1:
        raise CatalogError('Unknown project: '+query if not matches else 'Ambiguous project; choose '+', '.join(r['name'] for r in matches))
    return matches[0]


def resume_status(op):
    resume = op.get('resume')
    if resume is None: return {'state': 'unknown', 'message': 'No resume target recorded.', 'can_open': False}
    problems = _resume_errors(resume, op.get('location'))
    if problems: return {'state': 'invalid', 'message': '; '.join(problems), 'can_open': False}
    kind, target = resume['kind'], resume['target']
    if kind in ('url', 'command'):
        return {'state': 'unverified', 'message': 'Availability is unverified; no network or runtime probe was run.', 'can_open': False}
    p = Path(target)
    try:
        if Path(op['location']).resolve() != Path(op['location']):
            return {'state': 'invalid', 'message': 'Project location now resolves to a different path. Review its identity before opening.', 'can_open': False}
        if not p.exists(): return {'state': 'missing', 'message': 'Saved target is missing. Open the project location or choose a new target.', 'can_open': False}
        if not p.resolve().is_relative_to(Path(op['location']).resolve()):
            return {'state': 'invalid', 'message': 'Target now points outside its owning project.', 'can_open': False}
        if kind == 'file':
            if not p.is_file() or p.stat().st_size > 8_000_000:
                return {'state': 'invalid', 'message': 'Target is not a small readable document.', 'can_open': False}
            digest = hashlib.sha256(p.read_bytes()).hexdigest()
            if digest != resume['sha256']: return {'state': 'changed', 'message': 'Document changed since its saved observation. Review it and save the target again to refresh.', 'can_open': False}
            # Never hand executable source, HTML, or binaries to an OS open handler.
            if p.suffix.lower() not in ('.md', '.txt', '.pdf', '.json', '.rst') and p.name != 'README':
                return {'state': 'manual', 'message': 'This file type requires manual opening.', 'can_open': False}
        elif not p.is_dir(): return {'state': 'missing', 'message': 'Saved directory is no longer a directory.', 'can_open': False}
        return {'state': 'available', 'message': 'Target exists'+(' and its saved content matches.' if kind == 'file' else '.'), 'can_open': True}
    except (OSError, RuntimeError, ValueError) as error:
        return {'state': 'unreadable', 'message': f'Target cannot be checked: {error}', 'can_open': False}


def _available_suites():
    # Missing release/manifests must not hide an otherwise valid saved return point.
    try:
        return registry.load_suites()
    except (OSError, ValueError, KeyError):
        return {}


def project_view(row, suites=None):
    op = row['operator']
    missing = [field for field in ('purpose', 'resume', 'next_action', 'done_for_now') if not op.get(field)]
    if op['attention'] is None: missing.append('attention selection')
    suite = (suites if suites is not None else _available_suites()).get(row.get('primary_suite')) if row.get('primary_suite') else None
    evidence = {'suite_id': suite['id'], 'recorded_state': suite['state'], 'wave_claims': [{'id':w['id'],'kind':w.get('recovery_claim',{}).get('kind'),'level':w.get('recovery_claim',{}).get('level'),'runtime_followup':w.get('runtime_followup')} for w in suite['waves']]} if suite else None
    return {**op, 'suite_evidence': evidence, 'suite_evidence_error': 'Suite manifest unavailable; no evidence inferred.' if row.get('primary_suite') and not suite else None, 'name': row['name'], 'home_label': HOMES[op['primary_home']], 'attention_label': ATTENTION[op['attention']],
            'resume_status': resume_status(op), 'location_exists': Path(op['location']).is_dir(), 'incomplete': missing,
            'migration': {'enrolled': row.get('disposition') != 'catalog-only',
                          'primary_suite': row.get('primary_suite'), 'disposition': row.get('disposition'),
                          'migration': row.get('migration'), 'source_snapshot': row.get('source_snapshot')},
            'evidence_links': ['portfolio/project-ledger.json', 'portfolio/release-ledger.json', 'portfolio/recovery-program.json'] +
                              ([row['primary_suite']+'/suite.json'] if row.get('primary_suite') else [])}


def operator_action(ledger=None):
    doc = ledger if ledger is not None else load_catalog_ledger()
    selected = sorted((r for r in catalog_rows(doc) if r['operator']['attention'] == 'now'), key=lambda r: r['operator']['now_order'])
    if not selected: return {'actionable': False, 'project': None, 'message': 'No Now project selected. Choose up to three in Your projects or use ./s now PROJECT.'}
    view = project_view(selected[0])
    problems = []
    if not view['next_action']: problems.append('next action is unknown')
    if not view['done_for_now']: problems.append('done-for-now condition is unknown')
    if view['resume_status']['state'] not in ('available', 'unverified'): problems.append(view['resume_status']['message'])
    return {'actionable': not problems, 'project': view, 'message': '; '.join(problems) if problems else view['next_action']}


def catalog_view():
    doc = load_catalog_ledger()
    suites = _available_suites() if any(r.get('primary_suite') for r in catalog_rows(doc)) else {}
    return {'schema_version': '1.0.0', 'observed_at': doc['catalog']['observed_at'], 'homes': HOMES, 'now_limit': NOW_LIMIT,
            'projects': [project_view(r, suites) for r in catalog_rows(doc)], 'action': operator_action(doc),
            'unresolved': doc['catalog']['unresolved'], 'app_entries': doc['catalog']['app_entries']}


def render_ledger(doc):
    """Keep project-per-line layout required by the existing fingerprint updater."""
    head = {k:v for k,v in doc.items() if k not in ('projects', 'catalog_additions')}
    text = json.dumps(head, indent=2, ensure_ascii=False)[:-2]+',\n'
    for idx, key in enumerate(('projects', 'catalog_additions')):
        text += '  '+json.dumps(key)+': [\n'+',\n'.join('    '+json.dumps(r, separators=(',', ':'), ensure_ascii=False) for r in doc[key])+'\n  ]'+(',' if idx == 0 else '')+'\n'
    return (text+'}\n').encode('utf-8')


def prepare_resume(kind, target, location):
    if not isinstance(target, str) or not target.strip() or len(target) > 8000 or not isinstance(kind, str): raise CatalogError('Choose a target type and nonempty target text.')
    if Path(location).resolve() != Path(location): raise CatalogError('Project location changed identity. Review the canonical path first.')
    resume = {'kind': kind, 'target': target, 'observed_at': dt.datetime.now(ZoneInfo('America/Chicago')).date().isoformat(), 'sha256': None}
    if kind in ('file', 'directory'):
        p = Path(target).expanduser()
        p = p if p.is_absolute() else Path(location)/p
        p = p.resolve()
        if not p.is_relative_to(Path(location).resolve()) or not p.exists(): raise CatalogError('Choose an existing target within the project location.')
        resume['target'] = str(p)
        if kind == 'file':
            if not p.is_file() or p.stat().st_size > 8_000_000: raise CatalogError('Choose a document under 8 MB.')
            resume['sha256'] = hashlib.sha256(p.read_bytes()).hexdigest()
        elif not p.is_dir(): raise CatalogError('Choose a directory.')
    errors = _resume_errors(resume, location)
    if errors: raise CatalogError('; '.join(errors))
    return resume


def update_project(query, changes, expected_revision=None):
    if not isinstance(changes, dict) or not changes or set(changes)-EDITABLE:
        raise CatalogError('Update only operator attention, purpose, and resume fields.')
    with registry._ledger_lock():
        directory_fd = open_confined_directory(registry.SUITES_ROOT, 'portfolio')
        try:
            fd = os.open('project-ledger.json', os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd)
            with os.fdopen(fd, 'rb') as stream:
                mode = stat.S_IMODE(os.fstat(stream.fileno()).st_mode)
                before = stream.read()
            doc = json.loads(before)
            errors = validate_catalog(doc)
            if errors: raise CatalogError('; '.join(errors))
            row = resolve_project(query, doc); op = row['operator']
            if expected_revision is not None and (type(expected_revision) is not int or expected_revision != op['revision']):
                raise CatalogConflict('This record changed in another session. Reload; your draft has not been saved.')
            previous = {r['name']:json.dumps(r['operator'], sort_keys=True) for r in catalog_rows(doc)}
            patch = dict(changes)
            for key in TEXT_FIELDS:
                if key in patch and isinstance(patch[key], str): patch[key] = patch[key].strip() or None
            if 'resume' in patch and patch['resume'] is not None:
                val = patch['resume']
                if not isinstance(val, dict): raise CatalogError('resume must be an object or null')
                patch['resume'] = prepare_resume(val.get('kind'), val.get('target'), op['location'])
            attention = patch.get('attention', op['attention'])
            if attention is not None and (not isinstance(attention, str) or attention not in ATTENTION): raise CatalogError('Choose Now, In use, Waiting, Parked, or unassigned.')
            op.update(patch)
            others = sorted((r['operator'] for r in catalog_rows(doc) if r is not row and r['operator']['attention']=='now'), key=lambda x:x['now_order'])
            if attention == 'now':
                if len(others) >= NOW_LIMIT: raise CatalogError('Now already has three projects. Move one to In use, Waiting, Parked, or unassigned first.')
                order = patch.get('now_order', op['now_order'] or len(others)+1)
                if type(order) is not int or not 1 <= order <= min(NOW_LIMIT, len(others)+1): raise CatalogError('Choose an available Now position (1–3).')
                others.insert(order-1, op)
            else:
                if patch.get('now_order') is not None: raise CatalogError('Only Now may have an order.')
                op['now_order'] = None
            for index, selected in enumerate(others, 1): selected['now_order'] = index
            now = dt.datetime.now(dt.timezone.utc).isoformat()
            for r in catalog_rows(doc):
                if json.dumps(r['operator'], sort_keys=True) != previous[r['name']]:
                    r['operator']['revision'] += 1
                    r['operator']['updated_at'] = now
                    r['operator']['update_source'] = 'explicit local operator edit; not release approval'
            errors = validate_catalog(doc)
            if errors: raise CatalogError('; '.join(errors))
            temp = write_temp_payload(directory_fd, 'project-ledger.json', render_ledger(doc), mode=mode)
            try:
                commit_replacement(directory_fd, 'project-ledger.json', temp, expected_digest=hashlib.sha256(before).hexdigest())
            except OccupantConflict as error:
                raise CatalogConflict('The ledger changed while saving. Concurrent work was preserved; reload before retrying.') from error
            except CommitUncertain as error:
                raise CommitUnverified('Save reached its commit point but durability is unverified. Reload before retrying. '+str(error)) from error
            finally:
                temp.close()
            return project_view(row)
        finally:
            os.close(directory_fd)


def open_resume(query, expected_revision=None):
    row = resolve_project(query); op = row['operator']
    if expected_revision is not None and expected_revision != op['revision']: raise CatalogConflict('Resume record changed. Reload before opening.')
    status = resume_status(op)
    if not status['can_open']: raise CatalogError(status['message'])
    target = op['resume']['target']
    opener = '/usr/bin/open' if sys.platform == 'darwin' else 'xdg-open'
    # Only explicit CLI --open or an origin-checked button reaches this side effect.
    try:
        result = subprocess.run([opener, target], timeout=10, capture_output=True, text=True, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise CatalogError(f'Could not open the target. Open it manually: {target} ({error})') from error
    if result.returncode: raise CatalogError('The system opener failed. Open manually: '+target)
    return {'opened': target, 'message': 'Sent the target to the system opener; runtime or application success is unverified.'}


def release_overview():
    from .release_state import load_release_ledger, resolve_release_state
    from .recovery_program import load_recovery_program
    return resolve_release_state(load_release_ledger(), load_recovery_program(), registry.load_suites())


def print_project(view):
    print(f"{view['name']} · {view['home_label']} · {view['attention_label']}")
    print('Purpose:', view['purpose'] or 'Unknown — review needed')
    print('Owner:', view['owner']); print('Location:', view['location'])
    print('Next:', view['next_action'] or 'Unknown — no action invented')
    if view['waiting_trigger']: print('Waiting trigger:', view['waiting_trigger'])
    print('Done for now:', view['done_for_now'] or 'Unknown — choose a stopping point')
    if view['restart_note']: print('Restart note:', view['restart_note'])
    print('Resume:', (view['resume'] or {}).get('target', 'Unknown'))
    print('Target:', view['resume_status']['state'], '—', view['resume_status']['message'])
    if view['incomplete']: print('Incomplete:', ', '.join(view['incomplete']))
    if view['suite_evidence']:
        evidence = view['suite_evidence']
        print('Recorded suite evidence:', ', '.join(w['id']+' '+str(w['level']) for w in evidence['wave_claims']))
    print('Release / evidence remain separate:', ', '.join(view['evidence_links']))


def add_cli(sub):
    projects = sub.add_parser('projects', aliases=['p'], help='find projects by name, purpose, or stable home')
    projects.add_argument('query', nargs='?', default='')
    projects.add_argument('--home', choices=list(HOMES)); projects.add_argument('--json', action='store_true')
    project = sub.add_parser('project', help='show or save one restart record')
    project.add_argument('target'); project.add_argument('--json', action='store_true')
    for flag in ('purpose', 'next', 'done', 'trigger', 'note'): project.add_argument('--'+flag)
    project.add_argument('--attention', choices=['now', 'in-use', 'waiting', 'parked', 'unassigned'])
    project.add_argument('--order', type=int); project.add_argument('--revision', type=int)
    project.add_argument('--resume'); project.add_argument('--kind', choices=['file', 'directory', 'url', 'command'], default='file')
    now = sub.add_parser('now', aliases=['n'], help='show Now, or select a project; ceiling three')
    now.add_argument('target', nargs='?'); now.add_argument('--order', type=int); now.add_argument('--json', action='store_true')
    action = sub.add_parser('action', aliases=['a'], help='one operator action in chosen Now order (release next is unchanged)')
    action.add_argument('--json', action='store_true')
    resume = sub.add_parser('resume', aliases=['r'], help='show resume target; --open deliberately opens a verified document or folder')
    resume.add_argument('target', nargs='?'); resume.add_argument('--open', action='store_true'); resume.add_argument('--json', action='store_true')


def run_cli(args):
    try:
        cmd = args.command
        if cmd in ('projects', 'p'):
            doc = load_catalog_ledger(); q = args.query.casefold()
            rows = [project_view(r) for r in catalog_rows(doc)]
            rows = [r for r in rows if (not args.home or r['primary_home']==args.home) and q in ' '.join([r['name'], r['purpose'] or '', r['home_label']]).casefold()]
            if args.json: print(json.dumps(rows, indent=2))
            else:
                for r in rows: print(f"{r['name']} · {r['home_label']} · {r['attention_label']}" + (' · identity '+r['identity_status'] if r['identity_status']!='observed' else ''))
                print(f'{len(rows)} entries. Detail: ./s project NAME. Select: ./s now NAME.')
            return 0
        if cmd in ('action', 'a'):
            result = operator_action()
            if args.json: print(json.dumps(result, indent=2))
            elif result['project']: print_project(result['project']); print('Action status:', result['message'])
            else: print(result['message'])
            if not args.json:
                try: print('Release blockers remain:', release_overview()['open_blocker_count'], '(./s next)')
                except (ValueError, OSError) as error: print('Release state unavailable:', error)
            return 0 if result['actionable'] else 2
        if cmd in ('now', 'n'):
            if args.target:
                changes = {'attention':'now'}
                if args.order is not None: changes['now_order'] = args.order
                result = update_project(args.target, changes)
                print(json.dumps(result, indent=2)) if args.json else print_project(result)
            else:
                doc = load_catalog_ledger()
                selected = sorted((project_view(r) for r in catalog_rows(doc) if r['operator']['attention']=='now'), key=lambda r:r['now_order'])
                if args.json: print(json.dumps(selected, indent=2))
                elif not selected: print(operator_action(doc)['message'])
                else:
                    for r in selected: print(f"{r['now_order']}. {r['name']} — {r['next_action'] or 'Next action unknown'}")
            return 0
        if cmd in ('resume', 'r'):
            target = args.target
            if target is None:
                action = operator_action()
                if action['project'] is None: raise CatalogError(action['message'])
                target = action['project']['id']
            view = project_view(resolve_project(target))
            result = open_resume(target, view['revision']) if args.open else view
            if args.json: print(json.dumps(result, indent=2))
            elif args.open: print(result['message'])
            else: print_project(view)
            return 0
        changes = {}
        for flag, field in [('purpose','purpose'),('next','next_action'),('done','done_for_now'),('trigger','waiting_trigger'),('note','restart_note'),('order','now_order')]:
            if getattr(args, flag) is not None: changes[field] = getattr(args, flag)
        if args.attention is not None: changes['attention'] = None if args.attention=='unassigned' else args.attention
        if args.resume is not None: changes['resume'] = {'kind':args.kind,'target':args.resume} if args.resume else None
        view = update_project(args.target, changes, args.revision) if changes else project_view(resolve_project(args.target))
        print(json.dumps(view, indent=2)) if args.json else print_project(view)
        return 0
    except (CatalogError, OSError, ValueError) as error:
        print('ERROR:', error)
        return 2
