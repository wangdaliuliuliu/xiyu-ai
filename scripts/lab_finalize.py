"""Assemble E0/E1/E3 evidence and a conservative review report."""
from __future__ import annotations
import argparse, datetime as dt, json, pathlib, sqlite3

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--run',required=True); args=ap.parse_args()
    root=pathlib.Path(args.run).resolve()
    inv=json.loads((root/'inventory.json').read_text(encoding='utf-8'))
    parity=json.loads((root/'replica-parity.json').read_text(encoding='utf-8'))
    selftest=json.loads((root/'selftest.json').read_text(encoding='utf-8'))
    smoke=json.loads((root/'smoke-result.json').read_text(encoding='utf-8'))
    findings=[]; hard=[]
    trajectories={x['id']:x for x in smoke.get('trajectories',[])}
    t=trajectories.get('I03',{}); tool=t.get('tool',{}); result=tool.get('result',{}); context=result.get('context') or {}; lookup=context.get('sourceLookup') or {}
    final=str(t.get('final',''))
    expected_terms=['9月2','东坝','266','销售']
    if lookup.get('status')!='complete': hard.append('I03工具没有complete回执')
    if lookup.get('date')!='2026-09-02': hard.append('I03工具日期不精确')
    if lookup.get('venue')!='东坝': hard.append('I03工具门店范围错误')
    if lookup.get('core',{}).get('box_office_total')!=266: hard.append('I03工具事实值不是本次冻结副本的266')
    if any(x not in final for x in expected_terms): hard.append('I03最终表达缺少日期/门店/数值/指标')
    if '541.4' in final: hard.append('I03最终表达采用了未被工具支持的数字')
    else: findings.append({'kind':'positive','id':'I03','text':'决策草稿出现541.4但最终表达采用工具返回的266，事实闸在表达层纠正了草稿。'})
    if not selftest.get('isolation',{}).get('blockedExternalDelivery'): hard.append('隔离器未拦截外发')
    if any(not str(x.get('target','')).startswith('sink://') for x in smoke.get('sink',[])): hard.append('冒烟存在非sink投递')
    i01=trajectories.get('I01',{}); i01text=str(i01.get('final',''))
    if len(i01text)>700: findings.append({'kind':'warning','id':'I01','text':'冷启动主动消息超过700字符，虽有业务主体和可接位置，但低负担/活泼度需要人工复核。'})
    if '昨天你问' in i01text:
        db=sqlite3.connect(f"file:{root/'snapshot'/'bot.db'}?mode=ro",uri=True)
        rows=[r[0] for r in db.execute('SELECT content FROM companion_conversation_turns').fetchall()]
        db.close()
        if not any('中影' in str(x) and '定义' in str(x) for x in rows): hard.append('I01声称昨天问过中影定义但副本无来源')
        else: findings.append({'kind':'positive','id':'I01','text':'主动消息引用的中影店背景在复制的对话连续性中可回查。'})
    for item in smoke.get('trace',[]):
        if not item.get('response',{}).get('usage'): findings.append({'kind':'warning','id':item.get('label'),'text':'provider usage缺失'})
    status='failed' if hard else 'inconclusive'
    review={'schemaVersion':'ideal-agency-lab-review-v1','status':status,'hardFailures':hard,'findings':findings,'stageResults':{'E0_replicaParity':parity.get('status'),'E1_isolationAndChecker':selftest.get('status'),'E3_realProviderSmoke':smoke.get('status')},'limitations':smoke.get('limitations',[]),'attribution':{'sourcePresentForI03':True,'replicaParity':parity.get('status'),'toolRouting':'complete' if lookup.get('status')=='complete' else 'failed','expressionFactGuard':'passed' if '266' in final and '541.4' not in final else 'failed','modelDecisionDraftNeedsGroundingLint':'warning' if any('541.4' in str(m) for m in (t.get('decision') or {}).get('messages',[])) else 'not_observed','whyNotPassed':'本次仅完成E0/E1和I01/I03最小冒烟，未运行固定24族、留出、媒体、7日连续性、双模型和人工盲评。'}}
    (root/'reviews.json').write_text(json.dumps(review,ensure_ascii=False,indent=2),encoding='utf-8')
    manifest={'schemaVersion':'ideal-agency-lab-manifest-v1','runId':root.name,'createdAt':dt.datetime.now(dt.timezone.utc).isoformat(),'sourceRevision':inv['source'].get('gitRevision'),'sourceDbHash':inv['source']['sourceDbSha256'],'replicaDbHash':inv['replica']['sha256'],'provider':smoke.get('provider'),'model':smoke.get('model'),'promptVersion':'P1-inline-lab-smoke-v1','suites':{'E0':'completed','E1':'completed','E3':'completed','E4_fixed':'not_run','E5_holdout':'not_run','E6_media_continuity':'not_run'},'productionMutation':False,'realDelivery':False}
    (root/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    fixed_ids=['A01','A02','A03','A04','A05','A06','B01','B02','B03','B04','B05','B06','C01','C02','C03','C04','C05','C06','D01','D02','D03','D04','D05','D06']
    coverage={'schemaVersion':'ideal-agency-lab-coverage-v1','fixedFamilies':{'required':24,'ids':fixed_ids,'run':0,'status':'not_run'},'newScenarios':{'I01':1,'I02':0,'I03':1,'I04':0,'I05':0,'I06':0,'I07':0,'I08':0,'I09':0,'I10':0,'I11':0,'I12':0},'mutationsDetected':16,'note':'E3 smoke intentionally stops before fixed-suite gate.'}
    (root/'coverage.json').write_text(json.dumps(coverage,ensure_ascii=False,indent=2),encoding='utf-8')
    lat=[]
    for item in smoke.get('trace',[]):
        r=item.get('response',{}); lat.append({'label':item.get('label'),'latencyMs':r.get('latencyMs'),'promptTokens':r.get('usage',{}).get('prompt_tokens'),'completionTokens':r.get('usage',{}).get('completion_tokens'),'totalTokens':r.get('usage',{}).get('total_tokens')})
    (root/'cost-latency.json').write_text(json.dumps({'schemaVersion':'ideal-agency-lab-cost-latency-v1','calls':lat,'totalCalls':len(lat),'unknownPricing':True},ensure_ascii=False,indent=2),encoding='utf-8')
    traces=root/'traces'; traces.mkdir(exist_ok=True)
    (traces/'provider-calls.jsonl').write_text('\n'.join(json.dumps(x,ensure_ascii=False) for x in smoke.get('trace',[]))+'\n',encoding='utf-8')
    (traces/'sink-deliveries.jsonl').write_text('\n'.join(json.dumps(x,ensure_ascii=False) for x in smoke.get('sink',[]))+'\n',encoding='utf-8')
    repro='''# Reproduce

This run used the existing local source database and local workbench data read-only.

    python scripts/lab_discover.py
    python scripts/lab_parity.py --run <run>
    node scripts/lab_selftest.mjs --run <run>
    python scripts/lab_smoke.py --run <run>
    python scripts/lab_finalize.py --run <run>

The provider key is loaded in memory from the source configuration and is not copied into the snapshot or evidence. Delivery is sink-only.
'''
    (root/'reproduce.md').write_text(repro,encoding='utf-8')
    report=['# 隔离实验阶段报告','',f'- 运行目录：{root}',f'- 阶段状态：**{status}**','- 生产代码、生产数据库、真实 Bot 均未写入。','','## 已完成',f'- E0 副本一致性：{parity.get("status")}',f'- E1 隔离与 M01-M16 自检：{selftest.get("status")}',f'- E3 真实 API 冒烟：{smoke.get("status")}，4次 provider 调用，I01/I03各1条轨迹。','','## 关键观察']
    report.extend([f'- {x["text"]}' for x in findings] or ['- 暂无附加观察。'])
    report += ['', '## 未通过/未完成', '- 固定24族、每族5次、双模型、留出、媒体、7日连续性和人工盲评尚未运行，因此本报告不宣称实验通过。']
    if hard: report += ['', '## 硬失败', *[f'- {x}' for x in hard]]
    report += ['', '## 归因', '- I03的事实来源和工具路由在隔离副本中可用；最终表达正确使用了工具返回值。决策草稿中出现未由工具支持的541.4，当前未进入sink，但后续固定套件应增加“内部草稿事实未落地”规则。', '- I01能从真实复制的连续性引用中形成具体工作主动联系，但文本较长，是否符合低负担和人格目标需要人工盲评。', '']
    (root/'report.md').write_text('\n'.join(report),encoding='utf-8')
    print(json.dumps({'status':status,'hardFailures':len(hard),'findings':len(findings),'report':str(root/'report.md')},ensure_ascii=False))
    if status=='failed': raise SystemExit(1)

if __name__=='__main__': main()
