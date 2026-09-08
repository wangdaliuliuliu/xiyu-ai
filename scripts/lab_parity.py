"""E0 parity check for a completed lab snapshot."""
from __future__ import annotations
import argparse, datetime as dt, hashlib, json, pathlib, re, sqlite3

def sha(p):
    h=hashlib.sha256()
    with open(p,'rb') as f:
        for c in iter(lambda:f.read(1024*1024),b''): h.update(c)
    return h.hexdigest()

def redact(v, key=''):
    if re.search(r'token|secret|password|api.?key|authorization|cookie|session|private', key, re.I): return '[REDACTED]'
    if isinstance(v,list): return [redact(x,key) for x in v]
    if isinstance(v,dict): return {k:redact(x,k) for k,x in v.items()}
    return v

def norm_json(path):
    try: return redact(json.loads(pathlib.Path(path).read_text(encoding='utf-8')))
    except Exception: return None

def tables(conn):
    result={}
    for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table'"):
        try: result[name]=conn.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0]
        except sqlite3.Error: result[name]=None
    return result

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--run',required=True); args=ap.parse_args()
    root=pathlib.Path(args.run).resolve(); inv=json.loads((root/'inventory.json').read_text(encoding='utf-8'))
    source=pathlib.Path(inv['source']['sourceDbPath']); replica=root/'snapshot'/'bot.db'
    source_now=sha(source); conn=sqlite3.connect(f'file:{source.as_posix()}?mode=ro',uri=True); rep=sqlite3.connect(f'file:{replica.as_posix()}?mode=ro',uri=True)
    src_tables, rep_tables=tables(conn),tables(rep)
    allowed={'app_settings','wechat_accounts','ilink_context_tokens','pending_bind_sessions'}
    table_diffs=[]
    for name in sorted(set(src_tables)|set(rep_tables)):
        if src_tables.get(name)!=rep_tables.get(name):
            table_diffs.append({'table':name,'source':src_tables.get(name),'replica':rep_tables.get(name),'expectedScrub':name in allowed})
    core_tables=['companions','companion_memories','companion_conversation_turns','companion_open_loops','companion_current_works','companion_daily_schedule','companion_emotion_state','companion_life_state','companion_preferences','companion_sleep_schedule','enterprise_proactive_policies','proactive_runtime_schedules','wechat_messages']
    core_rows=[]
    for name in core_tables:
        if name not in src_tables or name not in rep_tables: core_rows.append({'table':name,'status':'unavailable'}); continue
        core_rows.append({'table':name,'source':src_tables[name],'replica':rep_tables[name],'status':'present' if src_tables[name]==rep_tables[name] else 'replica_failure'})
    source_data=root/'source-data'; copied_data=root/'snapshot'/'workbench-data'; file_checks=[]
    for file in copied_data.rglob('*'):
        if not file.is_file() or file.suffix.lower()!='.json': continue
        rel=file.relative_to(copied_data); original=source_data/rel
        if original.exists(): file_checks.append({'file':str(rel),'status':'equal_after_redaction' if norm_json(original)==norm_json(file) else 'replica_failure','sourceSha256':sha(original),'replicaSha256':sha(file)})
        else: file_checks.append({'file':str(rel),'status':'source_unavailable'})
    # Keep an unredacted-ish source-data tree only in the private run directory; the
    # discoverer creates it in later versions. For this run compare against the
    # workbench source directly when source-data was not materialized.
    if not source_data.exists():
        workbench=pathlib.Path(inv['workbench']['root'])/'data'
        file_checks=[]
        for file in copied_data.rglob('*'):
            if not file.is_file() or file.suffix.lower()!='.json': continue
            rel=file.relative_to(copied_data); original=workbench/rel
            if original.exists(): file_checks.append({'file':str(rel),'status':'equal_after_redaction' if norm_json(original)==norm_json(file) else 'replica_failure','sourceSha256':sha(original),'replicaSha256':sha(file)})
    conn.close(); rep.close()
    profile_ok=next((x for x in file_checks if x['file']=='strategy-project-profile.json'),None)
    status='passed' if source_now==inv['source']['sourceDbSha256'] and not [x for x in table_diffs if not x['expectedScrub']] and all(x['status'] in {'equal_after_redaction','source_unavailable'} for x in file_checks) and (not profile_ok or profile_ok['status']=='equal_after_redaction') and all(x['status']!='replica_failure' for x in core_rows) else 'failed'
    report={'schemaVersion':'ideal-agency-lab-replica-parity-v1','status':status,'checkedAt':dt.datetime.now(dt.timezone.utc).isoformat(),'sourceHashUnchanged':source_now==inv['source']['sourceDbSha256'],'sourceDbHashAtDiscovery':inv['source']['sourceDbSha256'],'sourceDbHashNow':source_now,'tableDiffs':table_diffs,'coreRows':core_rows,'workbenchJsonChecks':file_checks,'interpretation':{'scrubbedCredentialTablesAllowed':sorted(allowed),'sourceAndReplicaBusinessDataMustMatch':True,'profileCheck':profile_ok}}
    (root/'replica-parity.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'status':status,'sourceHashUnchanged':report['sourceHashUnchanged'],'tableDiffs':len(table_diffs),'coreRows':len(core_rows),'workbenchChecks':len(file_checks),'failedChecks':sum(1 for x in file_checks if x['status']=='replica_failure')},ensure_ascii=False))
    if status!='passed': raise SystemExit(1)

if __name__=='__main__': main()

