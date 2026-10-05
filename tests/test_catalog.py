"""Focused control-layer checks; no donor runtimes or owner selections are used."""
import copy
import hashlib
import http.client
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from portfolio_suites import catalog, registry
from portfolio_suites.paths import CommitUnverified
from portfolio_suites.server import create_server
from portfolio_suites.txn import CommitUncertain, OccupantConflict


class CatalogFixture:
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.suites = self.root/'suites'
        (self.suites/'portfolio').mkdir(parents=True)
        original = registry.load_ledger()
        template = original['projects'][0]
        self.doc = {'schema_version':'1.0.0', 'snapshot_at':'historical', 'projects':[], 'catalog_additions':[],
                    'catalog':{'schema_version':'1.0.0','homes':catalog.HOMES,'now_limit':3,'observed_at':'2026-10-05','app_entries':[],'unresolved':[]}}
        for name in ['alpha', 'beta', 'gamma', 'delta']:
            location = self.root/name; location.mkdir()
            readme = location/'README.md'; readme.write_text('# '+name+'\n')
            row = copy.deepcopy(template); row['name'] = name
            row['source_snapshot'] = {'git':True,'head':'preserved','status_sha256':'unchanged'}
            row['operator'].update(id=name,location=str(location),purpose='A useful project.',primary_home='independent',related_suites=[],
                                   attention=None,now_order=None,next_action=None,done_for_now=None,waiting_trigger=None,revision=0,
                                   resume={'kind':'file','target':str(readme),'observed_at':'2026-10-05','sha256':hashlib.sha256(readme.read_bytes()).hexdigest()})
            self.doc['projects'].append(row)
        self.path = self.suites/'portfolio/project-ledger.json'; self.path.write_bytes(catalog.render_ledger(self.doc))
        self.patches = [patch.object(registry,'SUITES_ROOT',self.suites),patch.object(registry,'_LEDGER_PATH',self.path)]
        for p in self.patches: p.start()
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(lambda:[p.stop() for p in reversed(self.patches)])

class CatalogTests(CatalogFixture, unittest.TestCase):
    def test_persistence_survives_fresh_process_and_preserves_legacy_fields(self):
        before = copy.deepcopy(self.doc['projects'][0])
        catalog.update_project('al', {'attention':'now','next_action':'Review one page.','done_for_now':'One page reviewed.'})
        env = {**os.environ,'SUITES_ROOT':str(self.suites),'PYTHONPATH':str(Path(catalog.__file__).parents[1])}
        result = subprocess.run([sys.executable,'-m','portfolio_suites','project','alpha','--json'],env=env,capture_output=True,text=True,timeout=5)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        view = json.loads(result.stdout)
        self.assertEqual(view['next_action'],'Review one page.'); self.assertEqual(view['attention'],'now')
        after = registry.load_ledger()['projects'][0]
        self.assertEqual({k:v for k,v in before.items() if k!='operator'},{k:v for k,v in after.items() if k!='operator'})

    def test_attention_cap_reorder_and_exit_do_not_change_release_disposition(self):
        for name in ['alpha','beta','gamma']: catalog.update_project(name,{'attention':'now'})
        before = self.path.read_bytes()
        with self.assertRaisesRegex(catalog.CatalogError,'three'): catalog.update_project('delta',{'attention':'now'})
        self.assertEqual(before,self.path.read_bytes())
        catalog.update_project('gamma',{'attention':'now','now_order':1})
        self.assertEqual(catalog.operator_action()['project']['id'],'gamma')
        catalog.update_project('gamma',{'attention':'parked'})
        self.assertEqual(catalog.operator_action()['project']['id'],'alpha')
        gamma = catalog.resolve_project('gamma')
        self.assertEqual(gamma['disposition'],self.doc['projects'][2]['disposition'])
        self.assertIsNone(gamma['operator']['now_order'])
        self.assertEqual(catalog.resolve_project('alpha')['operator']['now_order'],1)

    def test_waiting_requires_trigger_and_never_automatically_promotes(self):
        with self.assertRaisesRegex(catalog.CatalogError,'trigger'): catalog.update_project('alpha',{'attention':'waiting'})
        catalog.update_project('alpha',{'attention':'waiting','waiting_trigger':'Ryan supplies the result.'})
        self.assertEqual(catalog.resolve_project('alpha')['operator']['attention'],'waiting')
        self.assertFalse(catalog.operator_action()['actionable'])

    def test_missing_manifests_cannot_hide_saved_return_point(self):
        doc = registry.load_ledger()
        doc['projects'][0]['primary_suite'] = 'operator-os'
        self.path.write_bytes(catalog.render_ledger(doc))
        with patch.object(registry, 'load_suites', side_effect=FileNotFoundError('missing manifest')):
            view = catalog.project_view(catalog.resolve_project('alpha'))
            self.assertIsNone(view['suite_evidence'])
            self.assertIn('unavailable', view['suite_evidence_error'])
            self.assertEqual(view['resume_status']['state'], 'available')
            self.assertEqual(len(catalog.catalog_view()['projects']), 4)

    def test_unknown_action_and_stopping_point_are_explicit(self):
        catalog.update_project('alpha',{'attention':'now'})
        action = catalog.operator_action()
        self.assertFalse(action['actionable']); self.assertIn('unknown',action['message'])
        self.assertIsNone(action['project']['next_action'])

    def test_revision_conflict_preserves_concurrent_session(self):
        catalog.update_project('alpha',{'next_action':'First saved action.'},0)
        with self.assertRaises(catalog.CatalogConflict): catalog.update_project('alpha',{'next_action':'Stale overwrite.'},0)
        self.assertEqual(catalog.resolve_project('alpha')['operator']['next_action'],'First saved action.')

    def test_concurrent_now_writers_keep_ceiling(self):
        results = []
        def select(name):
            try: catalog.update_project(name,{'attention':'now'}); results.append('ok')
            except catalog.CatalogError: results.append('refused')
        threads = [threading.Thread(target=select,args=(name,)) for name in ['alpha','beta','gamma','delta']]
        for thread in threads: thread.start()
        for thread in threads: thread.join(timeout=30)
        self.assertEqual(results.count('ok'),3); self.assertEqual(results.count('refused'),1)
        self.assertEqual(catalog.validate_catalog(registry.load_ledger()),[])

    def test_precommit_interruption_keeps_complete_old_record(self):
        before = self.path.read_bytes()
        with patch.object(catalog,'write_temp_payload',side_effect=OSError('interrupted')):
            with self.assertRaises(OSError): catalog.update_project('alpha',{'attention':'parked'})
        self.assertEqual(self.path.read_bytes(),before)
        self.assertEqual(catalog.load_catalog_ledger()['projects'][0]['operator']['attention'],None)

    def test_commit_conflict_and_uncertainty_are_distinguished(self):
        with patch.object(catalog,'commit_replacement',side_effect=OccupantConflict('concurrent')):
            with self.assertRaises(catalog.CatalogConflict): catalog.update_project('alpha',{'attention':'parked'})
        with patch.object(catalog,'commit_replacement',side_effect=CommitUncertain('directory sync failed')):
            with self.assertRaisesRegex(CommitUnverified,'durability'): catalog.update_project('alpha',{'attention':'parked'})

    def test_missing_changed_and_symlink_targets_cannot_open(self):
        op = catalog.resolve_project('alpha')['operator']; readme = Path(op['resume']['target'])
        readme.write_text('changed')
        self.assertEqual(catalog.resume_status(op)['state'],'changed')
        with patch.object(catalog.subprocess,'run') as run:
            with self.assertRaises(catalog.CatalogError): catalog.open_resume('alpha')
            run.assert_not_called()
        readme.unlink(); self.assertEqual(catalog.resume_status(op)['state'],'missing')
        outside = self.root/'outside.md'; outside.write_text('outside')
        readme.symlink_to(outside)
        self.assertEqual(catalog.resume_status(op)['state'],'invalid')

    def test_attention_edit_does_not_reobserve_changed_target(self):
        op = catalog.resolve_project('alpha')['operator']; Path(op['resume']['target']).write_text('changed')
        view = catalog.update_project('alpha',{'attention':'in-use'})
        self.assertEqual(view['resume_status']['state'],'changed')
        view = catalog.update_project('alpha',{'resume':{'kind':'file','target':'README.md'}})
        self.assertEqual(view['resume_status']['state'],'available')

    def test_open_is_explicit_no_shell_and_disallowed_target_types_do_not_run(self):
        with patch.object(catalog.subprocess,'run') as run:
            catalog.project_view(catalog.resolve_project('alpha')); run.assert_not_called()
            run.return_value.returncode = 0
            catalog.open_resume('alpha',0)
            self.assertNotIn('shell',run.call_args.kwargs)
            self.assertEqual(run.call_args.args[0][-1],str(self.root/'alpha/README.md'))
        for resume in [{'kind':'url','target':'javascript:alert(1)'},{'kind':'file','target':str(self.root/'beta/README.md')},{'kind':'file','target':None}]:
            with self.assertRaises(catalog.CatalogError): catalog.update_project('alpha',{'resume':resume})
        catalog.update_project('alpha',{'resume':{'kind':'command','target':'./local-launcher'}})
        with patch.object(catalog.subprocess,'run') as run:
            with self.assertRaises(catalog.CatalogError): catalog.open_resume('alpha')
            run.assert_not_called()

    def test_invalid_inputs_fail_without_mutation(self):
        before = self.path.read_bytes()
        for changes in [{'attention':True},{'attention':[]},{'attention':'now','now_order':True},{'disposition':'retired'},{'attention':'parked','now_order':1},{'purpose':[]},{}]:
            with self.assertRaises(catalog.CatalogError): catalog.update_project('alpha',changes)
        self.assertEqual(before,self.path.read_bytes())

    def test_short_names_fail_on_ambiguity_and_app_alias_resolves_identity(self):
        doc = registry.load_ledger()
        doc['catalog']['app_entries']=[{'project':'alpha','label':'My project'}]
        self.assertEqual(catalog.resolve_project('my project',doc)['name'],'alpha')
        doc['catalog_additions']=[copy.deepcopy(doc['projects'][0])]
        doc['catalog_additions'][0]['name']='other/alpha'
        with self.assertRaisesRegex(catalog.CatalogError,'Ambiguous'): catalog.resolve_project('al',doc)

    def test_format_remains_compatible_with_baseline_updates(self):
        updated,names = registry.apply_snapshot_updates(self.path.read_text(),{'alpha':{'git':True,'head':'new'}})
        self.assertEqual(names,['alpha'])
        result = json.loads(updated)
        self.assertEqual(result['projects'][0]['operator'],self.doc['projects'][0]['operator'])


class CatalogAPITests(CatalogFixture, unittest.TestCase):
    def test_api_shared_persistence_origin_revision_and_release_boundary(self):
        server = create_server(port=0)
        thread = threading.Thread(target=server.serve_forever,daemon=True); thread.start()
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        port = server.server_address[1]
        def request(method,path,body=None,headers=None):
            connection = http.client.HTTPConnection('127.0.0.1',port,timeout=5)
            connection.request(method,path,json.dumps(body) if body else None,headers or {})
            response = connection.getresponse(); value = json.loads(response.read()); connection.close()
            return response.status,value
        status,data = request('GET','/api/catalog')
        self.assertEqual(status,200); self.assertEqual(len(data['projects']),4)
        body={'name':'alpha','revision':0,'changes':{'attention':'now','next_action':'Review one page.','done_for_now':'Page reviewed.'}}
        status,_=request('POST','/api/catalog/update',body,{'Origin':'https://other.example','Content-Type':'application/json'})
        self.assertEqual(status,403); self.assertEqual(catalog.resolve_project('alpha')['operator']['revision'],0)
        status,data=request('POST','/api/catalog/update',body)
        self.assertEqual(status,200); self.assertTrue(catalog.operator_action()['actionable'])
        status,_=request('POST','/api/catalog/update',body); self.assertEqual(status,409)
        status,_=request('POST','/api/catalog/update',{'name':'alpha','revision':1,'changes':{'release_phase':'supported'}}); self.assertEqual(status,400)
        with patch.object(catalog.subprocess,'run') as run:
            status,_=request('GET','/api/catalog/project?name=alpha'); self.assertEqual(status,200)
            status,_=request('POST','/api/catalog/open',{'name':'alpha','revision':1},{'Origin':'https://other.example'}); self.assertEqual(status,403)
            run.assert_not_called()


class ReconciledCatalogTests(unittest.TestCase):
    def test_live_inventory_recognizes_catalog_additions_without_donor_execution(self):
        doc = registry.load_ledger()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            rows = catalog.catalog_rows(doc)
            for row in rows:
                name = row['name']
                if '/' not in name and row['operator']['identity_status'] != 'missing': (root/name).mkdir()
            markers = {r['name'] for r in rows if r['operator']['inventory_kind']=='nested_repository'}
            walk = [(str(root/name),['.git'],[]) for name in markers]
            with patch.object(registry,'PROJECTS_ROOT',root), patch.object(registry,'check_project_git_drift',return_value=None) as probe, patch.object(registry.os,'walk',return_value=walk):
                report = registry.validate_registry(check_live=True)
            self.assertEqual(report.errors,[])
            self.assertTrue(any('unresolved' in warning for warning in report.warnings))
            self.assertEqual(probe.call_count,len(doc['projects']))

    def test_inventory_placements_shortcuts_and_existing_enrollment(self):
        doc = registry.load_ledger(); self.assertEqual(catalog.validate_catalog(doc),[])
        self.assertEqual(len(doc['projects']),70)
        rows = catalog.catalog_rows(doc); self.assertEqual(len(rows),len({r['operator']['location'] for r in rows}))
        expected = {'jev-a11y':'accessibility','jev-box':'model-behavior-lab','audio-house':'production-house','ming':'agent-reliability',
                    'the-website-factory':'brand-publishing','in-the-age-of-ai':'brand-publishing','carmen':'game-design','lewis-and-clark-dnd':'game-design',
                    'glowforge-it':'independent','Tally':'independent','open-pickleball-tourney':'independent','nonsense/bone-appetit':'independent'}
        for name,home in expected.items(): self.assertEqual(catalog.resolve_project(name,doc)['operator']['primary_home'],home)
        self.assertEqual(catalog.resolve_project('nonsense',doc)['operator']['inventory_kind'],'container')
        self.assertTrue(any(e.get('reason') and e.get('project') is None for e in doc['catalog']['app_entries']))
        for suite in registry.load_suites().values():
            for member in suite['members']: self.assertIsNotNone(catalog.resolve_project(member['project'],doc))
