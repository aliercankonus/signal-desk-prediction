import importlib.util,json,hashlib,os,tempfile
from pathlib import Path
from dataclasses import make_dataclass,fields,asdict
from types import SimpleNamespace
import pytest
ROOT=Path(__file__).resolve().parents[2]
s=importlib.util.spec_from_file_location('recovered',ROOT/'ops/bridge_one_shot/recovered_runner_binding.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)

def fixture(w):
    P=make_dataclass('FixturePlan',[(k,object) for k in ('attempt','uid','gid','bundle','auth','home','source','runner','state','inbox','signer_policy','journal_parent','signer_state_root','merge')])
    old=P(m.OLD,os.geteuid(),os.getegid(),*[w/(m.OLD+'-runtime-v2-'+k) if k in ('bundle','auth','home') else w/k for k in ('bundle','auth','home','source','runner','state','inbox','signer_policy','journal_parent','signer_state_root')],'42db985bba2f0a64ce8d848e39a11c2a18c689f3')
    root=w/m.ATTEMPT;rec=root/m.RECOVERY;rec.mkdir(parents=True)
    def put(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v))
    raw={k:str(v) if isinstance(v,Path) else v for k,v in asdict(old).items()};put(w/(m.OLD+'-runtime-v2-plan.json'),raw);put(w/(m.OLD+'-bootstrap-spec.json'),raw)
    for p in (root/'journals',root/'state/queue',rec/'runner/.git'):p.mkdir(parents=True,exist_ok=True)
    head=rec/'runner/.git/HEAD';head.write_text(m.PIN+'\n');head.chmod(0o644)
    digest='a'*64
    put(rec/'intent.json',dict(schema=1,pin=m.PIN,old_prefix_sha256=digest,task=False,runtime=False))
    put(rec/'ready.json',dict(schema=1,pin=m.PIN,source_refs_unchanged=True,old_prefix_sha256=digest,source_state={'ref':'fixed'},prepared_runner=True,task=False,runtime=False,signing=False,timer=False))
    report=json.dumps(m.expected_report(),sort_keys=True,separators=(',',':'))
    put(rec/'report-intent.json',{'body_sha256':hashlib.sha256(report.encode()).hexdigest()});put(rec/'report-receipt.json',{'id':m.RECEIPT,'verified':True})
    policy={'repo':m.REPO,'branch':'issue43-one-shot-a2'};put(root/'stage-intent.json',dict(instruction_id=m.INSTRUCTION,policy=policy,retry=False))
    put(root/'signer-policy.json',dict(repo=m.REPO,task_issue=43,body_digest=hashlib.sha256(b'fixture frozen body').hexdigest(),app_id=1144995,authority_identity=m.AUTH,runner_commit=m.PIN,start='2026-11-12T00:00:00Z',cursors={'41':m.INSTRUCTION-1,'45':6713729283}))
    body='fixture frozen body';calls=[]
    client=SimpleNamespace(comment=lambda *a:dict(id=m.RECEIPT,issue_url='https://api.github.com/repos/'+m.REPO+'/issues/41',body=report,user={'id':35579049},created_at='fixed',updated_at='fixed'),task=lambda *a:dict(state='open',body=body))
    recovery=SimpleNamespace(private_dir=lambda *a:None,blob=lambda p:p.read_bytes(),snapshot=lambda p:digest,refs=lambda p:{'ref':'fixed'})
    host=SimpleNamespace(fields=fields,Plan=P,trusted_worker_mount=lambda *a:None)
    a2=SimpleNamespace(DIGEST=hashlib.sha256(body.encode()).hexdigest(),POLICY=policy,instruction=lambda *a:{'created_at':'2026-11-12T00:00:00Z'},binding=lambda *a:calls.append('binding'))
    return old,root,rec,dict(host=host,recovery=recovery,a2=a2,client=client,uid=os.geteuid(),gid=os.getegid()),calls

def test_read_only_binding_preserves_all_existing_files_and_returns_proposal():
    with tempfile.TemporaryDirectory(dir=Path.home()) as d:
        w=Path(d);old,root,rec,kw,calls=fixture(w)
        before={p:p.read_bytes() for p in w.rglob('*') if p.is_file()}
        plan=m.bind(w,old,**kw)
        assert plan.runner==rec/'runner' and plan.home==old.home and plan.auth==root/'auth' and calls==['binding']
        assert all(p.read_bytes()==b for p,b in before.items()) and not (root/'plan.json').exists()

@pytest.mark.parametrize('change',['claim','queue','advanced','missing_receipt','changed_prefix','edited_report','head'])
def test_replayed_advanced_or_changed_state_refuses(change):
    with tempfile.TemporaryDirectory(dir=Path.home()) as d:
        w=Path(d);old,root,rec,kw,calls=fixture(w)
        if change=='claim':(root/'state/github-inbox').mkdir()
        elif change=='queue':(root/'state/queue/entry').touch()
        elif change=='advanced':(root/'runtime.json').write_text('{}')
        elif change=='missing_receipt':(rec/'report-receipt.json').unlink()
        elif change=='changed_prefix':kw['recovery'].snapshot=lambda p:'b'*64
        elif change=='edited_report':kw['client'].comment=lambda *a:{'id':m.RECEIPT,'body':'changed'}
        else:(rec/'runner/.git/HEAD').write_text('b'*40+'\n')
        with pytest.raises((m.Blocked,FileNotFoundError)):m.bind(w,old,**kw)
        assert not calls and not (root/'plan.json').exists()
