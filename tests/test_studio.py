import asyncio
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from pipeline_ui import app as backend, catalog, studio


class StudioTests(unittest.TestCase):
    def test_independent_lookup_and_pagination(self):
        first=catalog.lookup('popgen','panel','CHB');second=catalog.lookup('popgen','panel','CHB',30)
        self.assertGreater(first['total'],30);self.assertFalse({row[0] for row in first['rows']} & {row[0] for row in second['rows']})
        self.assertEqual(catalog.lookup('egene','hpo','HP:0001638')['rows'][0][0],'HP:0001638')
        if (catalog.ROOT/catalog.DISEASES).exists():self.assertTrue(catalog.lookup('egene','disease','BRCA1')['total'])
        node=catalog.lookup('gdgpt','nodes','BRCA1')['rows'][0];self.assertEqual(node[0],'BRCA1')
        result=catalog.lookup('gdgpt','edges',node[2]);self.assertTrue(result['total']);self.assertTrue(all(node[2] in (row[0],row[4]) for row in result['rows']))

    def test_allele_specific_real_zero_and_uncovered(self):
        with tempfile.TemporaryDirectory() as folder,patch.dict('os.environ',{'POPGEN_1000G_VCF_DIR':folder}):
            for alt,expected in [('A','0'),('CCCCTAA','0.00473934')]:
                out=catalog.lookup('popgen','allele','chr1:10397:C:'+alt,population='EUR');self.assertEqual(out['rows'][0][4],expected)
            with self.assertRaisesRegex(catalog.Problem,'no_panel_vcf'):catalog.lookup('popgen','allele','chr1:10397:C:G')

    def test_analyses(self):
        pop=catalog.calculate('popgen','EUR')['rows'];self.assertAlmostEqual(sum(row[3] for row in pop),100,places=1)
        result=catalog.calculate('egene','心肌病,not_an_HPO_term');self.assertEqual([row[1] for row in result['rows']],['HP:0001638',None]);self.assertTrue(catalog.calculate('gdgpt','BRCA1')['rows'])

    def test_notebook_persistence(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(catalog,'ROOT',Path(folder)),patch.object(catalog,'calculate',return_value={'rows':[],'source':'fixture'}):
            record=studio.notebook('create',module='popgen',value='CHB');self.assertEqual(studio.notebook('read',key=record['id']),record);self.assertEqual(studio.notebook('list')[0]['id'],record['id'])

    def test_browser_api_and_real_example_pipeline(self):
        async def flow():
            transport=httpx.ASGITransport(app=backend.app)
            async with httpx.AsyncClient(transport=transport,base_url='http://127.0.0.1') as client:
                self.assertEqual((await client.get('/')).status_code,200)
                self.assertEqual((await client.post('/api/example-run',headers={'Origin':'https://outside.invalid'})).status_code,403)
                self.assertEqual((await client.get('/api/query/egene?mode=classifications')).status_code,409)
                response=await client.post('/api/example-run',json={});self.assertEqual(response.status_code,202);job=response.json()['run_id']
                for _ in range(150):
                    snap=(await client.get('/api/runs/'+job)).json()
                    if snap['status'] in ('complete','failed'):break
                    await asyncio.sleep(.1)
                self.assertEqual(snap['status'],'complete',snap.get('error') or snap.get('log_tail'));self.assertTrue(snap['request']['synthetic_example'])
                self.assertEqual(set(snap['gdgpt_reports']),{'report.html','report_plain.html','report_graph.html'});self.assertTrue(snap['report_url'])
                for url in snap['gdgpt_reports'].values():self.assertEqual((await client.get(url)).status_code,200)
                self.assertEqual(catalog.lookup('egene','classifications','BRCA1',run=job,runs=backend.RUNS)['total'],1)
                self.assertEqual(catalog.lookup('egene','candidates',run=job,runs=backend.RUNS)['total'],0)
        with tempfile.TemporaryDirectory() as folder,patch.object(backend,'RUNS',Path(folder)):asyncio.run(flow())
