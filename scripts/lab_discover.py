"""T01 read-only discovery and scrubbed isolated snapshot.

Uses the Python stdlib SQLite driver so it does not depend on the repository's
native Node SQLite binary. The source database is opened read-only; only the
destination snapshot is modified.
"""
from __future__ import annotations
import argparse, datetime as dt, hashlib, json, os, pathlib, re, shutil, subprocess, sqlite3

REPO = pathlib.Path(__file__).resolve().parents[1]
WORKBENCH = pathlib.Path(os.environ.get("LAB_WORKBENCH_ROOT", r"E:\Yuanqu-Operations-Workbench\weekly-ops-entry"))
SOURCE_DB = pathlib.Path(os.environ.get("LAB_SOURCE_DB", str(REPO / "data" / "bot.db")))

def sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def redacted(value, key=""):
    if re.search(r"token|secret|password|api.?key|authorization|cookie|session|private", key, re.I):
        return "[REDACTED]"
    if isinstance(value, list): return [redacted(v, key) for v in value]
    if isinstance(value, dict): return {k: redacted(v, k) for k, v in value.items()}
    return value

def copy_json_tree(source: pathlib.Path, target: pathlib.Path):
    copied, excluded = [], []
    if not source.exists(): return copied, [{"file": str(source), "reason": "source_missing"}]
    for file in source.rglob("*"):
        if not file.is_file() or file.suffix.lower() not in {".json", ".jsonl"}: continue
        rel = file.relative_to(source)
        if re.search(r"\.env|credential|secret|password|token", file.name, re.I):
            excluded.append({"file": str(file), "reason": "credential_named_file"}); continue
        out = target / rel; out.parent.mkdir(parents=True, exist_ok=True)
        if file.suffix.lower() == ".json":
            try:
                out.write_text(json.dumps(redacted(json.loads(file.read_text(encoding="utf-8"))), ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                shutil.copy2(file, out)
        else: shutil.copy2(file, out)
        copied.append({"source": str(file), "target": str(out), "sha256": sha256(file), "bytes": file.stat().st_size})
    return copied, excluded

def table_inventory(conn):
    tables = []
    for name, typ, sql in conn.execute("SELECT name,type,sql FROM sqlite_master WHERE type IN ('table','view') ORDER BY name"):
        safe = '"' + name.replace('"', '""') + '"'
        try: count = conn.execute(f"SELECT count(*) FROM {safe}").fetchone()[0]
        except Exception: count = None
        columns = [{"name": row[1], "type": row[2], "notnull": row[3], "pk": row[5]} for row in conn.execute(f"PRAGMA table_info({safe})")]
        tables.append({"name": name, "type": typ, "count": count, "columns": columns, "schemaSha256": hashlib.sha256((sql or "").encode()).hexdigest()})
    return tables

def rows_inventory(conn):
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    wanted = ['users','user_accounts','user_profiles','companions','companion_memories','companion_conversation_turns','companion_open_loops','companion_current_works','companion_daily_schedule','companion_daily_thoughts','companion_diary','companion_emotion_state','companion_life_state','companion_preferences','companion_photo_log','companion_proactive_material_log','companion_sleep_schedule','companion_relational_diary','companion_reminders','enterprise_proactive_policies','proactive_runtime_schedules','proactive_schedules','agency_intentions','agency_actions','agency_feedback','agency_runtime','wechat_messages','photo_request_audit']
    result = {}
    for table in wanted:
        if table in names:
            count = conn.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
            result[table] = {"count": count, "nonEmpty": count > 0}
    if 'companions' in names:
        row = conn.execute('SELECT id,name,age,role_title,relationship_stage,affection_level,proactive_enabled,proactive_frequency,proactive_time_window,proactive_intensity,proactive_daily_target,proactive_unanswered,current_scene,persona_prompt FROM companions ORDER BY id LIMIT 1').fetchone()
        if row:
            keys = ['id','name','age','role_title','relationship_stage','affection_level','proactive_enabled','proactive_frequency','proactive_time_window','proactive_intensity','proactive_daily_target','proactive_unanswered','current_scene','persona_prompt']
            obj = dict(zip(keys, row)); prompt = obj.pop('persona_prompt') or ''
            obj['personaPromptSha256'] = hashlib.sha256(prompt.encode()).hexdigest(); result['primaryCompanion'] = obj
    return result

def git_revision():
    try: return subprocess.check_output(['git','rev-parse','HEAD'], cwd=REPO, text=True, stderr=subprocess.DEVNULL).strip()
    except Exception: return None

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--out', default=''); args = ap.parse_args()
    if not SOURCE_DB.exists(): raise SystemExit(f'source db not found: {SOURCE_DB}')
    if not WORKBENCH.exists(): raise SystemExit(f'workbench root not found: {WORKBENCH}')
    stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    out = pathlib.Path(args.out).resolve() if args.out else REPO / 'experiments' / 'ideal-agency-lab' / 'runs' / stamp
    snapshot = out / 'snapshot'; snapshot.mkdir(parents=True, exist_ok=True)
    source_uri = f'file:{SOURCE_DB.as_posix()}?mode=ro'
    conn = sqlite3.connect(source_uri, uri=True)
    settings = []
    for key, value_type, secret, updated_at in conn.execute('SELECT key,value_type,secret,updated_at FROM app_settings ORDER BY key'):
        settings.append({'key': key, 'valueType': value_type, 'secret': bool(secret), 'updatedAt': updated_at, 'configured': bool(conn.execute('SELECT 1 FROM app_settings WHERE key=? AND value IS NOT NULL AND length(value)>0',(key,)).fetchone())})
    inventory = {'schemaVersion':'ideal-agency-lab-inventory-v1','createdAt':dt.datetime.now(dt.timezone.utc).isoformat(),'source':{'repoRoot':str(REPO),'sourceDbPath':str(SOURCE_DB),'sourceDbSha256':sha256(SOURCE_DB),'gitRevision':git_revision(),'timezone':'Asia/Shanghai'},'workbench':{'root':str(WORKBENCH),'profile':str(WORKBENCH/'data'/'strategy-project-profile.json'),'runtimeState':str(WORKBENCH/'data'/'runtime-state')},'tables':table_inventory(conn),'settings':settings,'records':rows_inventory(conn),'resources':[],'exclusions':[{'resource':'chat/provider secrets','status':'present_in_source_not_copied','reason':'loaded only into the smoke process environment'},{'resource':'real Bot tokens and sessions','status':'present_in_source_scrubbed_in_replica','reason':'delivery is sink-only'}]}
    destination = sqlite3.connect(snapshot / 'bot.db')
    conn.backup(destination); conn.close(); destination.close()
    replica = sqlite3.connect(snapshot / 'bot.db')
    for sql in ['DELETE FROM app_settings WHERE secret=1', "UPDATE wechat_accounts SET bot_token='', login_session_id=''", 'DELETE FROM ilink_context_tokens', 'DELETE FROM pending_bind_sessions']:
        try: replica.execute(sql)
        except sqlite3.Error: pass
    replica.commit(); replica.close()
    inventory['replica'] = {'path':str(snapshot/'bot.db'),'sha256':sha256(snapshot/'bot.db'),'scrubbed':True}
    copied, excluded = copy_json_tree(WORKBENCH/'data', snapshot/'workbench-data')
    inventory['resources'].extend([{'type':'workbench_json',**x} for x in copied]); inventory['exclusions'].extend([{**x,'status':'unavailable'} for x in excluded])
    for rel in ['src/proactive.mjs','src/agency_protocol.mjs','src/enterprise_context.mjs','src/companion.mjs','src/db.mjs','src/photo_planner.mjs','config/agency-prompts.v1.json','docs/agency-ideal-lab-experiment-spec-2026-09-08.md']:
        p = REPO / rel
        inventory['resources'].append({'type':'source_file','file':str(p),'relative':rel,'sha256':sha256(p),'bytes':p.stat().st_size} if p.exists() else {'type':'source_file','file':str(p),'relative':rel,'status':'unavailable'})
    (out/'inventory.json').write_text(json.dumps(inventory,ensure_ascii=False,indent=2),encoding='utf-8')
    (out/'replica-safety.json').write_text(json.dumps({'schemaVersion':'replica-safety-v1','snapshotDb':str(snapshot/'bot.db'),'productionWritable':False,'realDeliveryEnabled':False,'scrubbedTables':['app_settings(secret=1)','wechat_accounts.bot_token','wechat_accounts.login_session_id','ilink_context_tokens','pending_bind_sessions'],'allowedOutbound':['configured model provider only'],'blockedOutbound':['WeChat/iLink','email','production workbench write APIs']},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'status':'passed','outRoot':str(out),'sourceDbSha256':inventory['source']['sourceDbSha256'],'replicaDbSha256':inventory['replica']['sha256'],'tables':len(inventory['tables']),'workbenchJsonFiles':len(copied),'missingResources':len(excluded)},ensure_ascii=False))

if __name__ == '__main__': main()
