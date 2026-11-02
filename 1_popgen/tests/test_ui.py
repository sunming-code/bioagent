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
                    if (result/'delivery/popgen_report.html').is_file():
                        self.assertIn('delivery/popgen_report.html',names)
                    pack=json.loads(z.read('delivery/evidence_pack.json'))
                    import posixpath
                    for relative in pack['files'].values():
                        if relative:
                            self.assertIn(posixpath.normpath('delivery/'+relative),names)
                self.assertEqual(client.get('/api/download/patient_vcf',params={'job_id':job}).status_code,200)

    def test_report_and_relative_download_routes(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(ui, 'JOBS', Path(tmp)):
            job = 'b' * 32
            directory = Path(tmp) / job
            delivery = directory / 'output/delivery'
            delivery.mkdir(parents=True)
            (delivery / 'popgen_report.html').write_text('<html>PopGen</html>')
            (delivery / 'evidence_pack.json').write_text('{}')
            (directory / 'output/patient.vcf.gz').write_bytes(b'synthetic')
            ui.write_job(directory, {'job_id': job, 'status': 'completed'})
            with TestClient(ui.app) as client:
                prefix = f'/reports/{job}/'
                self.assertEqual(client.get(prefix + 'delivery/popgen_report.html').status_code, 200)
                self.assertEqual(client.get(prefix + 'delivery/evidence_pack.json').status_code, 200)
                self.assertEqual(client.get(prefix + 'patient.vcf.gz').status_code, 200)
                self.assertEqual(client.get(prefix + '%2e%2e%2fjob.json').status_code, 404)
                ui.write_job(directory, {'job_id': job, 'status': 'running'})
                self.assertEqual(client.get(prefix + 'delivery/popgen_report.html').status_code, 409)

    def test_pipeline_report_links_resolve_to_run_local_files(self):
        from pipeline_ui import app as pipeline_ui
        from urllib.parse import urljoin
        with tempfile.TemporaryDirectory() as tmp, patch.object(pipeline_ui, 'RUNS', Path(tmp)):
            run = 'ui_synthetic_00000000'
            directory = Path(tmp) / run
            delivery = directory / 'output/delivery'
            (delivery / 'popgen').mkdir(parents=True)
            (directory / 'ui_state.json').write_text(json.dumps({'output_dir': str(directory / 'output')}))
            (delivery / 'index.html').write_text('<a href="popgen/report.html">PopGen</a>')
            (delivery / 'popgen/report.html').write_text('<a href="evidence_pack.json">evidence</a>')
            (delivery / 'popgen/evidence_pack.json').write_text('{}')
            (delivery / 'patient.vcf.gz').write_bytes(b'synthetic')
            with TestClient(pipeline_ui.app) as client:
                index = client.get(f'/api/runs/{run}/report')
                self.assertEqual(index.status_code, 200)
                report = client.get(urljoin(str(index.url), 'popgen/report.html'))
                self.assertEqual(report.status_code, 200)
                self.assertEqual(client.get(urljoin(str(report.url), 'evidence_pack.json')).status_code, 200)
                self.assertEqual(client.get(urljoin(str(report.url), '../patient.vcf.gz')).status_code, 200)
                artifact = client.get(f'/api/runs/{run}/artifacts', params={'path': 'delivery/popgen/report.html'})
                self.assertEqual(str(artifact.url), str(report.url))
                self.assertEqual(client.get(f'/api/runs/{run}/files/%2e%2e%2fui_state.json').status_code, 404)


if __name__=='__main__':
    unittest.main()
