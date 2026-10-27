"""Fictional HTTP acceptance/security tests; never use real app data."""
from pathlib import Path
import base64
import http.client
import io
import json
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from server import Application,make_server
from local_model import LocalModel,ModelError
from launch import outbound_guard

class ServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.app=Application(Path(self.tmp.name)/'fictional')
        self.server=make_server(self.app)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True); self.thread.start()
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.tmp.cleanup()
    def request(self,path='/api/state',data=None,headers=None,auth=True):
        conn=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=5)
        hs={'Content-Type':'application/json'}
        if auth: hs['Authorization']='Bearer '+self.server.token
        if headers: hs.update(headers)
        conn.request('GET' if data is None else 'POST',path,None if data is None else json.dumps(data),hs)
        r=conn.getresponse();content=r.read(); result=(r.status,dict(r.getheaders()),content);conn.close();return result
    def post(self,path,data):
        status,_,payload=self.request(path,data)
        self.assertEqual(status,200,payload)
        return json.loads(payload)
    def test_http_boundary(self):
        self.assertEqual(self.server.server_address[0],'127.0.0.1')
        self.assertEqual(self.request(auth=False)[0],401)
        self.assertEqual(self.request(headers={'Origin':'https://example.invalid'})[0],403)
        self.assertEqual(self.request(headers={'Host':'example.invalid'})[0],403)
        self.assertEqual(self.request(headers={'Sec-Fetch-Site':'cross-site'})[0],403)
        self.assertEqual(self.request('/../../settings.json')[0],404)
        self.assertEqual(self.request('/api/state')[0],200)
    def test_csp_and_no_remote_resources(self):
        status,headers,body=self.request('/',auth=False)
        self.assertEqual(status,200)
        self.assertIn("connect-src 'self'",headers['Content-Security-Policy'])
        self.assertEqual(headers['Cache-Control'],'no-store')
        self.assertNotIn(b'https://',body)
    def test_demo_review_save_reopen(self):
        proposal=self.post('/api/demo',{})
        self.assertEqual(self.app.store.state()['revision'],0)
        result=self.post('/api/approve',{'id':proposal['id'],'revision':proposal['base_revision']})
        self.assertGreater(len(result['transactions']),0)
        reopened=Application(self.app.root)
        self.assertEqual(reopened.store.state(),result)
        self.assertEqual(self.request('/api/approve',{'id':proposal['id'],'revision':proposal['base_revision']})[0],400)
    def test_import_preview_duplicate_and_versions(self):
        contents=b'date,description,amount,account,classification,category\n2026-01-01,Fictional salary,100.00,Demo,income,Salary\n'
        preview=self.post('/api/upload',{'name':'fictional.csv','base64':base64.b64encode(contents).decode()})
        self.assertEqual(self.app.documents,[])
        saved=self.post('/api/import',{'id':preview['id']})
        self.assertEqual(saved['version'],1)
        self.assertTrue(self.post('/api/import',{'id':preview['id']})['duplicate'])
        p=self.post('/api/import-propose',{'id':preview['id']})
        self.assertEqual(self.app.store.state()['revision'],0)
        self.post('/api/approve',{'id':p['id'],'revision':p['base_revision']})
        preview2=self.post('/api/upload',{'name':'fictional.csv','base64':base64.b64encode(contents+b'2026-01-02,Fictional rent,-50.00,Demo,expense,Housing\n').decode()})
        saved2=self.post('/api/import',{'id':preview2['id']})
        self.assertEqual(saved2['version'],2)
        self.assertEqual(self.app.get_doc(saved['id'])[1],contents)
    def test_export_all_formats_and_backup_no_session(self):
        p=self.post('/api/demo',{});self.post('/api/approve',{'id':p['id'],'revision':p['base_revision']})
        for fmt in ('xlsx','csv','html','json','backup'):
            out=self.post('/api/export',{'format':fmt})
            status,headers,content=self.request(out['url'])
            self.assertEqual(status,200);self.assertTrue(content)
            self.assertEqual(self.request(out['url'],auth=False)[0],401)
            if fmt=='backup':
                with zipfile.ZipFile(io.BytesIO(content)) as z:
                    self.assertIn('BACKUP-INFO.json',z.namelist())
                    self.assertFalse(any('session' in n or 'browser' in n for n in z.namelist()))
    def test_file_paths_and_mutations_rejected(self):
        for name in ('../secret.txt','x:secret.txt','x\\secret.txt','/secret.txt'):
            self.assertEqual(self.request('/api/upload',{'name':name,'base64':'eA=='})[0],400)
        self.assertEqual(self.request('/api/model/start',{'model':'foo-cloud'})[0],400)
        self.assertEqual(self.request('/api/shutdown',{})[0],400)
    def test_fictional_ai_proposal_not_saved(self):
        answer={'transactions':[{'date':'2026-01-01','description':'Fictional tea','amount':'-3.00','account':'Demo','classification':'expense','category':'Food','source':'Fictional note: tea $3'}],'questions':[],'warnings':['Verify source.']}
        with patch.object(self.app.model,'analyze',return_value=answer):
            result=self.post('/api/analyze',{'text':'Fictional tea $3 paid from Demo on 2026-01-01'})
        self.assertTrue(result['proposal']);self.assertEqual(self.app.store.state()['revision'],0)
    def test_external_network_audit_guard(self):
        for destination in ('example.com','8.8.8.8','::1'):
            with self.assertRaises(PermissionError):outbound_guard('socket.connect',(object(),(destination,80)))
        outbound_guard('socket.connect',(object(),('127.0.0.1',80)))

class ModelTests(unittest.TestCase):
    def test_cloud_name_and_metadata_rejected(self):
        model=LocalModel()
        for name in ('foo:cloud','https://example.com','../model',''):
            with self.assertRaises(ModelError):model.validate_name(name)
        with patch.object(model,'request',return_value={'remote_host':'example.com','model_info':{'general.parameter_count':100}}):
            with self.assertRaises(ModelError):model.verify_model('fictional:tiny')
        with patch.object(model,'request',return_value={'model_info':{'general.parameter_count':100}}):
            self.assertTrue(model.verify_model('fictional:tiny'))
    def test_bad_model_output_and_no_autoretry(self):
        model=LocalModel()
        with patch.object(model,'verify_model',return_value=True),patch.object(model,'request',return_value={'message':{'content':'not json'}}) as request:
            with self.assertRaises(ModelError):model.analyze('fictional note','fictional:tiny')
            self.assertEqual(request.call_count,1)
    def test_busy_refuses_second_prompt(self):
        model=LocalModel();model.busy.acquire()
        with self.assertRaises(ModelError):model.analyze('fictional note','fictional:tiny')
        model.busy.release()
    def test_incomplete_response_is_not_salvaged_or_saved(self):
        model=LocalModel()
        with patch.object(model,'verify_model',return_value=True),patch.object(model,'request',return_value={'done_reason':'length','message':{'content':'{}'}}):
            with self.assertRaisesRegex(ModelError,'length limit'):model.analyze('fictional note','fictional:tiny')
    def test_request_uses_bounded_structured_schema(self):
        model=LocalModel()
        with patch.object(model,'verify_model',return_value=True),patch.object(model,'request',return_value={'done_reason':'stop','message':{'content':'{"transactions":[],"questions":[],"warnings":[]}'}}) as request:
            model.analyze('fictional note','fictional:tiny')
            payload=request.call_args.args[1]
            self.assertEqual(payload['format']['properties']['warnings']['maxItems'],10)
            self.assertEqual(payload['format']['properties']['transactions']['maxItems'],100)

if __name__=='__main__':unittest.main()
