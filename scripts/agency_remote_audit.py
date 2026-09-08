"""Read-only incident evidence. Run on the documented Aliyun Xiyu host via SSH stdin.
Only whitelisted configuration and incident messages are emitted. No credentials.
"""
import datetime
import hashlib
import json
import pathlib
import sqlite3
import subprocess
import urllib.error
import urllib.request

root = pathlib.Path('/opt/xiyu-ai')
env = {}
for line in (root / '.env').read_text().splitlines():
    if '=' in line and not line.startswith('#'):
        key, value = line.split('=', 1)
        env[key.strip()] = value.strip().strip('"').strip("'")
report = {'checkedAt': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'operation': 'read-only', 'root': str(root)}
keys = ['XIYU_AGENCY_MODE', 'XIYU_WORKBENCH_CONTEXT_URL', 'XIYU_WORKBENCH_CONTEXT_ENABLED', 'XIYU_ENTERPRISE_PROACTIVE_ENABLED']
report['dotenvFlags'] = {key: env.get(key, '(unset)') for key in keys}
files = ['src/bot.mjs', 'src/enterprise_context.mjs', 'src/playground.mjs', 'src/proactive.mjs', 'src/agency_protocol.mjs', 'config/prompts/work-response-v1.json']
report['hashes'] = {file: hashlib.sha256((root / file).read_bytes()).hexdigest() if (root / file).exists() else 'MISSING' for file in files}
db = sqlite3.connect('file:/opt/xiyu-ai/data/bot.db?mode=ro', uri=True)
report['incidentMessages'] = db.execute("SELECT direction,content,created_at FROM wechat_messages WHERE created_at BETWEEN '2026-09-08 00:08:50' AND '2026-09-08 00:10:00' ORDER BY id").fetchall()
report['bindingOwnerIds'] = db.execute('SELECT account_id,user_id,companion_id,is_active FROM wechat_accounts').fetchall()
report['agencyTables'] = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'agency_%'").fetchall()
db.close()
report['service'] = subprocess.check_output(['systemctl', 'show', 'xiyu-ai.service', '-p', 'WorkingDirectory', '-p', 'ActiveEnterTimestamp', '-p', 'ActiveState'], text=True)
journal = subprocess.check_output(['journalctl', '-u', 'xiyu-ai.service', '--since', '2026-09-08 08:08:50', '--until', '2026-09-08 08:10:00', '--no-pager', '-o', 'cat'], text=True)
report['incidentBridgeLog'] = [line for line in journal.splitlines() if '[EnterpriseContext]' in line]
report['http'] = []
for suffix in ['/api/health', '/api/knowledge/catalog']:
    url = env['XIYU_WORKBENCH_CONTEXT_URL'].rstrip('/') + suffix
    req = urllib.request.Request(url, headers={'accept': 'application/json', 'x-xiyu-token': env.get('XIYU_WORKBENCH_CONTEXT_TOKEN', '')})
    try:
        with urllib.request.urlopen(req, timeout=18) as response:
            report['http'].append({'url': url, 'status': response.status, 'contentType': response.headers.get('Content-Type')})
    except urllib.error.HTTPError as error:
        report['http'].append({'url': url, 'status': error.code, 'contentType': error.headers.get('Content-Type'), 'bodyPrefix': error.read(180).decode(errors='replace')})
    except Exception as error:
        report['http'].append({'url': url, 'errorType': type(error).__name__})
print(json.dumps(report, ensure_ascii=False, indent=2))
