import io
import json
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from ui import app as ui


class UIIntegrationTests(unittest.TestCase):
    def test_invalid_input_runs_and_reports_failure_without_old_results(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(ui, 'JOBS', Path(tmp)):
            with TestClient(ui.app) as client:
                response=client.post('/api/upload-vcf',files={'file':('bad.vcf',b'not a VCF','text/plain')})
                self.assertEqual(response.status_code,202,response.text)
                job=response.json()['job_id']
                self.assertEqual(client.get('/api/dashboard',params={'job_id':job}).status_code,409)
                for _ in range(200):
                    state=client.get('/api/jobs/'+job).json()
                    if state['status'] in {'failed','completed'}:
                        break
                    time.sleep(0.1)
                self.assertEqual(state['status'],'failed',state)
                self.assertIn('error',state)
                self.assertEqual(client.get('/api/download/evidence_pack',params={'job_id':job}).status_code,409)
                self.assertEqual(client.get('/api/jobs/not-a-valid-id').status_code,404)

    def test_upload_names_cannot_collide(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(ui,'JOBS',Path(tmp)), patch.object(ui,'run_job'):
            with TestClient(ui.app) as client:
                ids=[]
                for _ in range(2):
                    r=client.post('/api/upload-vcf',files={'file':('same.vcf',b'input','text/plain')})
                    self.assertEqual(r.status_code,202)
                    ids.append(r.json()['job_id'])
                self.assertNotEqual(*ids)
                self.assertTrue(all((Path(tmp)/j/'input.vcf').read_bytes()==b'input' for j in ids))
                self.assertEqual(client.post('/api/upload-vcf',files={'file':('empty.vcf',b'','text/plain')}).status_code,400)

    def test_completed_dashboard_and_archive_references(self):
        result=ui.ROOT/'results/validation_current'
        if not (result/'delivery/evidence_pack.json').exists():
            self.skipTest('Full pipeline validation has not finished')
        with tempfile.TemporaryDirectory() as tmp, patch.object(ui,'JOBS',Path(tmp)):
            job='a'*32
            directory=Path(tmp)/job
            directory.mkdir()
            (directory/'output').symlink_to(result, target_is_directory=True)
            ui.write_job(directory,{'job_id':job,'status':'completed','filename':'validation.vcf','created_at':'2026-10-16T00:00:00Z'})
            with TestClient(ui.app) as client:
                r=client.get('/api/dashboard',params={'job_id':job})
                self.assertEqual(r.status_code,200,r.text)
                self.assertEqual(r.json()['sample']['id'],'NA18526')
                self.assertEqual(r.json()['sample']['alias'],'NA18526')
                self.assertTrue(r.json()['files']['patient_vcf'])
                r=client.get('/api/download-zip',params={'job_id':job})
                self.assertEqual(r.status_code,200,r.text)
                with zipfile.ZipFile(io.BytesIO(r.content)) as z:
                    names=set(z.namelist())
                    self.assertEqual(len(names),len(z.namelist()))
                    self.assertIn('patient.vcf.gz',names)
                    pack=json.loads(z.read('delivery/evidence_pack.json'))
                    import posixpath
                    for relative in pack['files'].values():
                        if relative:
                            self.assertIn(posixpath.normpath('delivery/'+relative),names)
                self.assertEqual(client.get('/api/download/patient_vcf',params={'job_id':job}).status_code,200)


if __name__=='__main__':
    unittest.main()
