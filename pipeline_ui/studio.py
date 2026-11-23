"""HTTP surface for independent module queries and reproducible reference notebooks."""
import json
import sqlite3
from datetime import datetime, timezone
from uuid import uuid4

from starlette.concurrency import run_in_threadpool
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import JSONResponse
from starlette.routing import Route

from . import catalog


class LocalOrigin(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.method not in ('GET','HEAD','OPTIONS'):
            origin=request.headers.get('origin')
            if (origin and origin!=str(request.base_url).rstrip('/')) or request.headers.get('sec-fetch-site')=='cross-site':
                return JSONResponse({'code':'local_only'},status_code=403)
        response=await call_next(request)
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Referrer-Policy']='no-referrer'
        if request.url.path.startswith('/api/'): response.headers['Cache-Control']='no-store'
        return response


middleware=[Middleware(TrustedHostMiddleware,allowed_hosts=['localhost','127.0.0.1','[::1]']),Middleware(LocalOrigin)]


def summary():
    graph=json.loads((catalog.ROOT/catalog.KG/'task_kg_summary.json').read_text())
    available=(catalog.ROOT/catalog.DISEASES).is_file()
    return {'revision':catalog.REVISION,'samples':len(catalog.dataset('panel')),'populations':len({row['SUBPOP'] for row in catalog.dataset('panel')}),'terms':len(catalog.dataset('hpo')),'associations':len(catalog.dataset('disease')) if available else None,'nodes':graph['node_count'],'edges':graph['edge_count'],'classes':graph['nodes_by_type'],'reference_fasta':(catalog.ROOT/'1_popgen/data/reference/GRCh38.fa').is_file()}


def notebook(action, *, module='', value='', key=''):
    folder=catalog.ROOT/'runs';folder.mkdir(exist_ok=True)
    with sqlite3.connect(folder/'reference-notebooks.sqlite') as db:
        db.execute('CREATE TABLE IF NOT EXISTS studies (id TEXT PRIMARY KEY, created TEXT NOT NULL, module TEXT NOT NULL, input TEXT NOT NULL, report TEXT NOT NULL)')
        if action=='create':
            if not isinstance(value,str) or len(value)>4000: raise catalog.Problem('invalid_query')
            report=catalog.calculate(module,value)
            record={'id':'ref_'+uuid4().hex,'created':datetime.now(timezone.utc).isoformat(timespec='seconds'),'module':module,'input':value,'revision':catalog.REVISION,'result':report}
            db.execute('INSERT INTO studies VALUES(?,?,?,?,?)',(record['id'],record['created'],module,value,json.dumps(record,ensure_ascii=False)));return record
        if action=='list':
            return [dict(zip(('id','created','module','input'),row)) for row in db.execute('SELECT id,created,module,input FROM studies ORDER BY rowid DESC LIMIT 100')]
        row=db.execute('SELECT report FROM studies WHERE id=?',(key,)).fetchone()
        if not row: raise catalog.Problem('unknown_record',404)
        return json.loads(row[0])


async def query(request):
    params=request.query_params
    try: offset=int(params.get('offset',0))
    except ValueError: raise catalog.Problem('invalid_query') from None
    data=await run_in_threadpool(catalog.lookup,request.path_params['module'],params.get('mode',''),params.get('q',''),offset,params.get('run',''),params.get('population','EUR'))
    return JSONResponse(data)


async def stats(request):return JSONResponse(await run_in_threadpool(summary))


async def studies(request):
    if request.method=='GET':return JSONResponse(await run_in_threadpool(notebook,'list'))
    try: body=await request.json()
    except (ValueError,UnicodeError): raise catalog.Problem('invalid_query') from None
    if not isinstance(body,dict) or not isinstance(body.get('module'),str):raise catalog.Problem('invalid_query')
    record=await run_in_threadpool(notebook,'create',module=body['module'],value=body.get('input',''))
    return JSONResponse(record,status_code=201)


async def study(request):
    key=request.path_params['key'];record=await run_in_threadpool(notebook,'read',key=key)
    if request.query_params.get('download')=='1':
        return JSONResponse(record,headers={'Content-Disposition':f'attachment; filename="{record["id"]}.json"'})
    return JSONResponse(record)


async def problem(request, exc):return JSONResponse({'code':exc.code},status_code=exc.status)


routes=[Route('/api/studio',stats),Route('/api/query/{module}',query),Route('/api/studies',studies,methods=['GET','POST']),Route('/api/studies/{key}',study)]
