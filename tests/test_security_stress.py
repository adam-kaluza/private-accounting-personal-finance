"""Fictional security/resource regressions. Never open an existing user session."""
from __future__ import annotations

import copy
import http.client
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

RELEASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(RELEASE/'app'))
import launch
import local_model
import server
from finance_core import FinanceError

ROW={'date':'2026-01-12','description':'Fictional tea','amount':'-3.00','account':'Demo',
     'classification':'expense','category':'Food','source':'Fictional note: tea 3.00'}
CSV=b'date,description,amount,account,classification,category\n2026-01-12,Fictional tea,-3.00,Demo,expense,Food\n'


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory(prefix='security-',dir=RELEASE/'tests')
        self.addCleanup(self.temporary.cleanup)
        self.parent=Path(self.temporary.name)
        self.app=server.Application(self.parent/'fictional')


class StorageAndRaceTests(Fixture):
    def test_ai_questions_are_attached_before_any_concurrent_approval(self):
        answer={'transactions':[copy.deepcopy(ROW)],'questions':['Which fictional source confirms the account?'],
                'warnings':['Review the fictional source.']}
        started=threading.Event(); finished=threading.Event(); errors=[]; workers=[]
        original=self.app.store.propose

        def propose_with_competing_approval(*args,**kwargs):
            proposal=original(*args,**kwargs)
            def approve():
                started.set()
                try: self.app.store.approve(proposal['id'],proposal['base_revision'])
                except FinanceError as error: errors.append(str(error))
                finally: finished.set()
            worker=threading.Thread(target=approve,daemon=True)
            workers.append(worker); worker.start()
            self.assertTrue(started.wait(3))
            self.assertFalse(finished.wait(.2),'A proposal was approved before its review questions existed')
            return proposal

        try:
            with mock.patch.object(self.app.model,'analyze',return_value=answer), \
                    mock.patch.object(self.app.store,'propose',side_effect=propose_with_competing_approval):
                result=self.app.route('/api/analyze',{'text':'Fictional source note'})
        finally:
            for worker in workers: worker.join(3)
        self.assertTrue(finished.is_set())
        self.assertEqual(len(errors),1)
        self.assertIn('unresolved review questions',errors[0])
        self.assertFalse(result['proposal']['valid'])
        self.assertEqual(self.app.store.state()['revision'],0)

    def test_import_annotation_failure_removes_incomplete_draft(self):
        preview=self.app.preview('fictional.csv',CSV)
        with mock.patch.object(self.app.store,'annotate',side_effect=FinanceError('Fictional review failure')):
            with self.assertRaises(FinanceError): self.app.route('/api/import-propose',{'id':preview['id']})
        self.assertEqual(self.app.store.pending(),[])
        self.assertEqual(self.app.store.state()['revision'],0)

    def test_failed_atomic_replace_cleans_only_its_temporary_file(self):
        path=self.app.root/'fictional-setting.json'
        path.write_bytes(b'Fictional original')
        before=set(self.app.root.iterdir())
        with mock.patch.object(server.os,'replace',side_effect=OSError('Fictional disk error')):
            with self.assertRaises(OSError): server.write_atomic(path,b'Fictional new value')
        self.assertEqual(path.read_bytes(),b'Fictional original')
        self.assertEqual(set(self.app.root.iterdir()),before)

    def test_backup_cumulative_size_is_bounded_without_writing_partial_export(self):
        for name in ('fictional-a.txt','fictional-b.txt'):
            (self.app.docroot/name).write_bytes(b'F'*40)
        with mock.patch.object(server,'MAX_BACKUP_BYTES',64):
            with self.assertRaisesRegex(ValueError,'exceeds'): self.app.export('backup')
        self.assertEqual(list(self.app.exports.iterdir()),[])
        self.assertEqual((self.app.docroot/'fictional-a.txt').read_bytes(),b'F'*40)

    def test_backup_file_count_is_bounded(self):
        for index in range(3): (self.app.docroot/f'fictional-{index}.txt').write_bytes(b'Fictional')
        with mock.patch.object(server,'MAX_BACKUP_FILES',2):
            with self.assertRaisesRegex(ValueError,'too many files'): self.app.export('backup')
        self.assertEqual(list(self.app.exports.iterdir()),[])

    def test_download_registry_bound_preserves_saved_exports(self):
        with mock.patch.object(server,'MAX_DOWNLOADS',2):
            exports=[self.app.export('json') for _ in range(3)]
        self.assertEqual(len(self.app.downloads),2)
        self.assertNotIn(exports[0]['url'].rsplit('/',1)[-1],self.app.downloads)
        for item in exports: self.assertTrue(Path(item['path']).is_file())

    def test_hard_linked_document_is_refused_even_when_hash_matches(self):
        preview=self.app.preview('fictional.csv',CSV)
        imported=self.app.route('/api/import',{'id':preview['id']})
        path=self.app.docroot/self.app.documents[0]['storage']
        original=self.parent/'fictional-original.csv'
        original.write_bytes(CSV)
        path.unlink()
        os.link(original,path)
        with self.assertRaisesRegex(ValueError,'Linked|redirected'): self.app.get_doc(imported['id'])
        self.assertEqual(original.read_bytes(),CSV)


class HTTPStressTests(Fixture):
    def setUp(self):
        super().setUp()
        self.http=server.make_server(self.app)
        self.worker=threading.Thread(target=self.http.serve_forever,daemon=True)
        self.worker.start()
        self.addCleanup(self.stop_server)

    def stop_server(self):
        self.http.shutdown(); self.http.server_close(); self.worker.join(3)

    def request(self,headers=None):
        connection=http.client.HTTPConnection('127.0.0.1',self.http.server_port,timeout=3)
        try:
            connection.request('GET','/api/state',headers=headers or {})
            response=connection.getresponse()
            return response.status,response.read()
        finally: connection.close()

    def raw(self,header_lines,body=b'',half_close=False):
        connection=socket.create_connection(('127.0.0.1',self.http.server_port),timeout=3)
        try:
            connection.sendall(('\r\n'.join(header_lines)+'\r\n\r\n').encode('latin-1')+body)
            if half_close: connection.shutdown(socket.SHUT_WR)
            response=http.client.HTTPResponse(connection); response.begin()
            return response.status,response.read()
        finally: connection.close()

    def headers(self):
        return ['POST /api/demo HTTP/1.1',f'Host: 127.0.0.1:{self.http.server_port}',
                'Authorization: Bearer '+self.http.token,'Content-Type: application/json']

    def test_non_ascii_authorization_returns_controlled_401(self):
        status,payload=self.request({'Authorization':'Bearer caf\xe9'})
        self.assertEqual(status,401)
        self.assertIn('error',json.loads(payload))

    def test_duplicate_origin_and_host_headers_are_refused(self):
        for extra in ('Host: attacker.invalid','Origin: http://attacker.invalid'):
            headers=self.headers()+[f'Origin: http://127.0.0.1:{self.http.server_port}',extra,'Content-Length: 2']
            self.assertEqual(self.raw(headers,b'{}')[0],403)
        self.assertEqual(self.app.store.pending(),[])

    def test_ambiguous_body_lengths_and_transfer_encoding_are_refused(self):
        for suffix in (['Content-Length: 2','Content-Length: 2'],
                       ['Content-Length: 2','Transfer-Encoding: chunked']):
            self.assertEqual(self.raw(self.headers()+suffix,b'{}')[0],400)
        self.assertEqual(self.app.store.pending(),[])

    def test_incomplete_upload_never_executes_even_if_prefix_is_valid_json(self):
        status,payload=self.raw(self.headers()+['Content-Length: 3'],b'{}',half_close=True)
        self.assertEqual(status,400)
        self.assertIn('incomplete',json.loads(payload)['error'])
        self.assertEqual(self.app.store.pending(),[])

    def test_stalled_body_times_out_without_mutation(self):
        before=time.monotonic()
        with mock.patch.object(server,'SOCKET_TIMEOUT',.2):
            status,_=self.raw(self.headers()+['Content-Length: 3'],b'{')
        self.assertEqual(status,400)
        self.assertLess(time.monotonic()-before,2)
        self.assertEqual(self.app.store.pending(),[])

    def test_connection_budget_rejects_excess_idle_clients_and_recovers(self):
        # Rebuild only this test's own empty HTTP fixture with two worker slots.
        self.stop_server()
        with mock.patch.object(server,'MAX_CONNECTIONS',2): self.http=server.make_server(self.app)
        self.worker=threading.Thread(target=self.http.serve_forever,daemon=True); self.worker.start()
        sockets=[]
        try:
            for _ in range(2):
                connection=socket.create_connection(('127.0.0.1',self.http.server_port),timeout=3)
                connection.sendall(b'GET /api/state HTTP/1.1\r\n')
                sockets.append(connection)
            deadline=time.monotonic()+3
            while self.http._slots._value and time.monotonic()<deadline: time.sleep(.01)
            self.assertEqual(self.http._slots._value,0)
            extra=socket.create_connection(('127.0.0.1',self.http.server_port),timeout=3)
            sockets.append(extra)
            self.assertEqual(extra.recv(1),b'')
        finally:
            for connection in sockets: connection.close()
        deadline=time.monotonic()+3
        while self.http._slots._value<2 and time.monotonic()<deadline: time.sleep(.01)
        self.assertEqual(self.request({'Authorization':'Bearer '+self.http.token})[0],200)

    def test_auth_gate_and_static_allowlist_do_not_expose_known_local_paths(self):
        for path in ('/session.json','/documents/index.json','/%2e%2e/settings.json',
                     '/api/download/../../settings.json','//api/state','/api/state?token='+self.http.token):
            connection=http.client.HTTPConnection('127.0.0.1',self.http.server_port,timeout=3)
            try:
                connection.request('GET',path)
                response=connection.getresponse(); response.read()
                self.assertIn(response.status,(401,404),path)
            finally: connection.close()

    def test_shutdown_drains_inflight_approval_before_returning_storage_ownership(self):
        proposal=self.app.store.propose('transaction',copy.deepcopy(ROW))
        entered=threading.Event(); release=threading.Event(); closed=threading.Event()
        original=self.app.route; client_errors=[]
        def route(path,data):
            entered.set()
            if not release.wait(5): raise AssertionError('Fictional writer was not released')
            return original(path,data)
        def approve():
            connection=http.client.HTTPConnection('127.0.0.1',self.http.server_port,timeout=5)
            try:
                connection.request('POST','/api/approve',json.dumps({'id':proposal['id'],'revision':0}),
                                   {'Authorization':'Bearer '+self.http.token,'Content-Type':'application/json'})
                connection.getresponse().read()
            except (OSError,http.client.HTTPException) as error: client_errors.append(type(error).__name__)
            finally: connection.close()
        def close():
            self.http.server_close(); closed.set()
        client=threading.Thread(target=approve,daemon=True)
        closer=threading.Thread(target=close,daemon=True)
        try:
            with mock.patch.object(self.app,'route',side_effect=route):
                client.start(); self.assertTrue(entered.wait(3))
                self.http.shutdown()
                closer.start()
                self.assertFalse(closed.wait(.2),'HTTP shutdown returned while an approval could still write')
                release.set(); closer.join(3); client.join(3)
        finally:
            release.set()
            if closer.ident: closer.join(3)
            client.join(3)
        self.assertTrue(closed.is_set())
        self.assertEqual(self.app.store.state()['revision'],1)

    def test_shutdown_interrupts_idle_socket_without_waiting_for_read_timeout(self):
        connection=socket.create_connection(('127.0.0.1',self.http.server_port),timeout=3)
        try:
            connection.sendall(b'GET / HTTP/1.1\r\n')
            deadline=time.monotonic()+3
            while not self.http._connections and time.monotonic()<deadline: time.sleep(.01)
            self.assertTrue(self.http._connections)
            self.http.shutdown()
            started=time.monotonic(); self.http.server_close()
            self.assertLess(time.monotonic()-started,2)
            self.assertEqual(len(self.http._connections),0)
        finally: connection.close()


class LauncherFailureTests(Fixture):
    def test_lock_file_hard_link_is_refused_before_any_bytes_are_written(self):
        original=self.parent/'fictional-empty-original.txt'; original.write_bytes(b'')
        os.link(original,self.app.root/'.app.lock')
        with self.assertRaisesRegex(ValueError,'Linked|redirected'): launch.acquire_lock(self.app.root)
        self.assertEqual(original.read_bytes(),b'')

    def test_startup_failure_releases_data_lock(self):
        with mock.patch.object(sys,'argv',['launch.py','--no-browser','--data-dir',str(self.app.root)]), \
                mock.patch.object(sys,'addaudithook'), \
                mock.patch.object(launch,'Application',side_effect=ValueError('Fictional invalid settings')):
            with self.assertRaises(ValueError): launch.main()
        lock=launch.acquire_lock(self.app.root)
        self.assertIsNotNone(lock)
        lock.close()

    def test_browser_startup_failure_closes_only_new_server_and_removes_its_session(self):
        fake_server=mock.Mock(server_port=12345,token='FICTIONAL-TOKEN')
        with mock.patch.object(sys,'argv',['launch.py','--data-dir',str(self.app.root)]), \
                mock.patch.object(sys,'addaudithook'), mock.patch.object(launch,'Application',return_value=self.app), \
                mock.patch.object(launch,'make_server',return_value=fake_server), \
                mock.patch.object(launch,'open_window',side_effect=OSError('Fictional browser failure')):
            with self.assertRaises(OSError): launch.main()
        fake_server.server_close.assert_called_once()
        fake_server.serve_forever.assert_not_called()
        self.assertFalse((self.app.root/'session.json').exists())
        lock=launch.acquire_lock(self.app.root)
        self.assertIsNotNone(lock)
        lock.close()


class ModelStressTests(unittest.TestCase):
    def test_untrusted_model_output_must_match_the_actual_requested_schema(self):
        valid={'transactions':[copy.deepcopy(ROW)],'questions':[],'warnings':[]}
        malformed=[{},dict(valid,extra='unrequested'),dict(valid,transactions=[ROW]*101),
                   dict(valid,questions=['Fictional question']*11),dict(valid,warnings=['F'*501]),
                   dict(valid,transactions=[dict(ROW,description='F'*1201)]),
                   dict(valid,transactions=[dict(ROW,amount='1e2')]),
                   dict(valid,transactions=[dict(ROW,classification='arbitrary')]),
                   dict(valid,transactions=[{k:v for k,v in ROW.items() if k!='source'}])]
        model=local_model.LocalModel()
        for value in malformed:
            with self.subTest(shape=str(value)[:100]), mock.patch.object(model,'verify_model',return_value=True), \
                    mock.patch.object(model,'request',return_value={'message':{'content':json.dumps(value)}}) as request:
                with self.assertRaises(local_model.ModelError): model.analyze('Fictional note','fictional:tiny')
                self.assertEqual(request.call_count,1)
                self.assertFalse(model.busy.locked())

    def test_invalid_text_never_contacts_even_the_local_model(self):
        model=local_model.LocalModel()
        with mock.patch.object(model,'verify_model') as verify:
            for text in ('', 'F'*24001, None):
                with self.assertRaises(local_model.ModelError): model.analyze(text,'fictional:tiny')
            verify.assert_not_called()

    def test_fake_parameter_metadata_is_not_local_model_proof(self):
        model=local_model.LocalModel()
        for count in (None,0,-1,True,'100',1.5):
            with mock.patch.object(model,'request',return_value={'model_info':{'general.parameter_count':count}}):
                with self.assertRaises(local_model.ModelError): model.verify_model('fictional:tiny')

    def test_http_redirect_is_rejected_without_following_location(self):
        model=local_model.LocalModel(); model.process=mock.Mock(); model.process.poll.return_value=None; model.port=12345
        connection=mock.Mock(); response=connection.getresponse.return_value
        response.status=302; response.read.return_value=b'{}'
        response.getheader.return_value='https://example.invalid/fictional'
        with mock.patch.object(local_model.http.client,'HTTPConnection',return_value=connection) as factory:
            with self.assertRaises(local_model.ModelError): model.request('/api/version')
        factory.assert_called_once_with('127.0.0.1',12345,timeout=10)
        self.assertEqual(connection.request.call_count,1)
        response.getheader.assert_not_called()
        connection.close.assert_called_once()

    def test_response_size_limit_is_applied_during_read(self):
        model=local_model.LocalModel(); model.process=mock.Mock(); model.process.poll.return_value=None; model.port=12345
        connection=mock.Mock(); response=connection.getresponse.return_value
        response.status=200; response.read.return_value=b'F'*2_000_001
        with mock.patch.object(local_model.http.client,'HTTPConnection',return_value=connection):
            with self.assertRaises(local_model.ModelError): model.request('/api/version')
        response.read.assert_called_once_with(2_000_001)
        connection.close.assert_called_once()

    def test_force_killed_owned_child_is_reaped_and_session_state_reset(self):
        model=local_model.LocalModel(); child=mock.Mock(); child.poll.return_value=None
        child.wait.side_effect=[subprocess.TimeoutExpired('fictional-owned-child',5),0]
        model.process=child; model.port=12345; model.model='fictional:tiny'
        model.close()
        child.terminate.assert_called_once(); child.kill.assert_called_once()
        self.assertEqual(child.wait.call_count,2)
        self.assertIsNone(model.process); self.assertIsNone(model.port); self.assertEqual(model.model,'')


if __name__=='__main__': unittest.main()
