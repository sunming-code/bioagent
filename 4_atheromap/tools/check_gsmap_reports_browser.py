#!/usr/bin/env python3
"""Open gsMap reports in Chromium and check plots, tables, images, and controls."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from playwright.sync_api import sync_playwright


def require(value, message):
    if not value:
        raise ValueError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    output = root/'validation/gsmap_real_samples'
    expected = json.loads((output/'result_validation.json').read_text())
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=['--no-sandbox','--disable-dev-shm-usage'])
        version = browser.version
        for numeric in expected['samples']:
            sample = numeric['sample']
            report = root/numeric['report']
            context = browser.new_context(viewport={'width':1600,'height':1200}, device_scale_factor=1)
            page = context.new_page()
            errors, failed, bad_http, console_errors = [], [], [], []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('requestfailed', lambda request: failed.append({'url':request.url,'failure':request.failure}))
            page.on('response', lambda response: bad_http.append({'url':response.url,'status':response.status}) if response.status>=400 else None)
            page.on('console', lambda message: console_errors.append(message.text) if message.type=='error' else None)
            page.goto(report.as_uri(), wait_until='load', timeout=45000)
            page.wait_for_function("""() => {
                const graphs=[...document.querySelectorAll('.plotly-graph-div')];
                return graphs.length===2 && graphs.every(g=>g._fullLayout&&g.data&&g.data.length>0);
            }""", timeout=30000)
            plot_info = page.evaluate("""() => [...document.querySelectorAll('.plotly-graph-div')].map(g=>({
                traces:g.data.length, points:g.data.reduce((s,t)=>s+(t.x?t.x.length:0),0),
                svg:g.querySelectorAll('svg.main-svg').length,
                canvas:g.querySelectorAll('canvas').length,
                title:g._fullLayout.title.text
            }))""")
            require(plot_info[0]['points']==numeric['n_spots'], f'{sample}: browser spatial plot misses spots')
            require(plot_info[1]['points']>=100000, f'{sample}: browser Manhattan data incomplete')
            require(page.locator('table').count()==2, f'{sample}: browser tables missing')
            require(page.locator('table').nth(0).locator('tbody tr').count()==numeric['n_groups'], f'{sample}: group table rows invalid')
            require(page.locator('table').nth(1).locator('tbody tr').count()==50, f'{sample}: gene table rows invalid')
            options=page.locator('#geneSelect option').evaluate_all('(xs)=>xs.map(x=>x.value)')
            require(len(options)==50, f'{sample}: gene selection incomplete')
            selected=[]
            for index in [0,24,49]:
                chosen = page.select_option('#geneSelect',value=options[index])
                require(chosen == [options[index]], f'{sample}: browser failed to select requested gene')
                page.wait_for_function("""() => ['expressionPlotImg','gssPlotImg'].every(id=>{
                    const im=document.getElementById(id);
                    return im.complete&&im.naturalWidth>200&&im.naturalHeight>200;
                })""",timeout=15000)
                images=page.locator('#genePlots img').evaluate_all('(xs)=>xs.map(x=>({src:x.getAttribute("src"),width:x.naturalWidth,height:x.naturalHeight}))')
                require(all(options[index] in image['src'] for image in images), f'{sample}: gene selector did not update plots')
                selected.append({'gene':options[index],'images':images})
            require(page.select_option('#geneSelect',value=options[0]) == [options[0]], f'{sample}: could not restore first gene')
            page.locator('[data-bs-toggle="collapse"]').click()
            page.wait_for_function("document.getElementById('runningInfo').classList.contains('show')",timeout=10000)
            require(page.locator('#runningInfo').is_visible(),f'{sample}: run parameter control not working')
            page.locator('h1').first.scroll_into_view_if_needed()
            page.wait_for_timeout(150)
            page.screenshot(path=str(output/f'{sample}_report_browser.png'),full_page=False)
            result=dict(sample=sample,status='passed' if not (errors or failed or bad_http or console_errors) else 'failed',report=numeric['report'],browser_version=version,plots=plot_info,gene_selector_checks=selected,run_parameters_toggle=True,page_errors=errors,failed_requests=failed,http_errors=bad_http,console_errors=console_errors,screenshot=f'validation/gsmap_real_samples/{sample}_report_browser.png')
            results.append(result)
            print(json.dumps(result,ensure_ascii=False),flush=True)
            context.close()
        browser.close()
    summary=dict(schema_version='1.0',status='passed' if all(r['status']=='passed' for r in results) else 'failed',validated_at=datetime.now(timezone.utc).isoformat(),browser_version=version,samples=results)
    (output/'browser_validation.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    require(summary['status']=='passed','Report browser checks failed; see browser_validation.json')


if __name__=='__main__':
    main()
