"""Minimal real-provider smoke for the isolated ideal-agency lab."""
from __future__ import annotations
import argparse, datetime as dt, hashlib, json, os, pathlib, sqlite3, subprocess, time, urllib.error, urllib.request

REPO = pathlib.Path(__file__).resolve().parents[1]

def sha(value):
    return hashlib.sha256(str(value).encode()).hexdigest()

def load_setting(conn, key):
    row = conn.execute("SELECT value FROM app_settings WHERE key=?", (key,)).fetchone()
    return row[0] if row else ""

def http_json(url, method="GET", body=None, timeout=45):
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode()
    req = urllib.request.Request(url, data=data, method=method, headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            raw = res.read().decode("utf-8", "replace")
            return res.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try: payload = json.loads(raw)
        except Exception: payload = {"raw": raw[:600]}
        return exc.code, payload

def provider_call(provider, model, key, system, messages, max_tokens=700, timeout=60):
    endpoints = {
        "deepseek": "https://api.deepseek.com/chat/completions",
        "openai": "https://api.openai.com/v1/chat/completions",
        "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        "zhipu": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
    }
    url = endpoints.get(provider)
    if not url:
        raise RuntimeError(f"unsupported_provider_for_lab:{provider}")
    used_model = model or ("deepseek-chat" if provider == "deepseek" else "gpt-4o-mini")
    body = {"model": used_model, "messages": [{"role": "system", "content": system}, *messages],
            "temperature": 0.55, "top_p": 0.9, "max_tokens": max_tokens}
    req = urllib.request.Request(url, data=json.dumps(body, ensure_ascii=False).encode(), method="POST",
                                 headers={"content-type": "application/json", "authorization": f"Bearer {key}"})
    started = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            payload = json.loads(res.read().decode("utf-8", "replace"))
        choice = (payload.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        return {"ok": True, "text": message.get("content") or "", "requestId": payload.get("id"),
                "finishReason": choice.get("finish_reason"), "usage": payload.get("usage") or {},
                "latencyMs": round((time.time() - started) * 1000)}
    except Exception as exc:
        return {"ok": False, "text": "", "error": str(exc).replace(key, "[REDACTED]")[:800],
                "latencyMs": round((time.time() - started) * 1000)}

def extract_json(text):
    text = str(text or "")
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start: return None
    try: return json.loads(text[start:end + 1])
    except Exception: return None

def start_workbench(run_root, runtime_dir, profile_path):
    port = 41870 + (os.getpid() % 900)
    workbench = pathlib.Path(os.environ.get("LAB_WORKBENCH_ROOT", r"E:\Yuanqu-Operations-Workbench\weekly-ops-entry"))
    module_path = (workbench / "backend" / "feishu-sync-server.mjs").resolve()
    js = (
        "import { pathToFileURL } from 'node:url';\n"
        f"process.env.WEEKLY_OPS_PORT={port!r}; process.env.WEEKLY_OPS_HOST='127.0.0.1';\n"
        f"process.env.WEEKLY_OPS_RUNTIME_STATE_DIR={str(runtime_dir)!r};\n"
        f"process.env.STRATEGY_PROFILE_PATH={str(profile_path)!r};\n"
        f"process.env.WEEKLY_OPS_SETTINGS_PATH={str(run_root / 'snapshot' / 'workbench-data' / 'weekly-ops-settings.json')!r};\n"
        "process.env.XIYU_CONTEXT_TOKEN='';\n"
        f"const mod=await import(pathToFileURL({str(module_path)!r}).href);"
        f"await new Promise(resolve=>mod.server.listen({port},'127.0.0.1',resolve));\n"
        "console.log('READY'); setInterval(()=>{}, 1e9);\n"
    )
    js_path = run_root / "workbench-lab-server.mjs"
    js_path.write_text(js, encoding="utf-8")
    proc = subprocess.Popen([os.environ.get("NODE_BINARY", "node"), str(js_path)],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            env=os.environ.copy())
    base = f"http://127.0.0.1:{port}"
    deadline, output = time.time() + 25, []
    while time.time() < deadline:
        if proc.stdout:
            line = proc.stdout.readline()
            if line: output.append(line.strip())
        status, data = http_json(base + "/api/knowledge/catalog", timeout=2)
        if status == 200 and isinstance(data.get("catalog"), dict):
            return proc, base, {"status": status, "data": data, "startup": output}
        time.sleep(.2)
    proc.terminate()
    raise RuntimeError(f"workbench_start_failed:{output[-5:]}")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    args = ap.parse_args()
    run_root = pathlib.Path(args.run).resolve()
    snapshot_db = run_root / "snapshot" / "bot.db"
    runtime_dir = run_root / "snapshot" / "workbench-data" / "runtime-state"
    profile_path = run_root / "snapshot" / "workbench-data" / "strategy-project-profile.json"
    if not snapshot_db.exists(): raise SystemExit("snapshot missing; run lab_discover.py first")
    source_db_path = pathlib.Path(os.environ.get("LAB_SOURCE_DB", str(REPO / "data" / "bot.db")))
    source = sqlite3.connect(f"file:{source_db_path.as_posix()}?mode=ro", uri=True)
    provider = os.environ.get("CHAT_PROVIDER") or load_setting(source, "CHAT_PROVIDER") or "deepseek"
    model = os.environ.get("CHAT_MODEL") or load_setting(source, "CHAT_MODEL")
    key_name = {"deepseek": "DEEPSEEK_API_KEY", "openai": "OPENAI_API_KEY",
                "qwen": "QWEN_API_KEY", "zhipu": "ZHIPU_API_KEY"}.get(provider, "")
    api_key = (os.environ.get(key_name) or load_setting(source, key_name)) if key_name else ""
    source.close()
    if not api_key: raise SystemExit(f"provider_not_configured:{provider}")
    started = dt.datetime.now(dt.timezone.utc).isoformat()
    trace, sink, proc = [], [], None
    try:
        proc, base, catalog_probe = start_workbench(run_root, runtime_dir, profile_path)
        catalog = catalog_probe["data"].get("catalog") or {}
        snapshot = sqlite3.connect(f"file:{snapshot_db.as_posix()}?mode=ro", uri=True)
        companion = snapshot.execute("SELECT id,name,age,role_title,relationship_stage,affection_level,current_scene,persona_prompt FROM companions ORDER BY id LIMIT 1").fetchone() or ()
        turns = [dict(zip(["role", "content", "created_at"], row))
                 for row in snapshot.execute("SELECT role,content,created_at FROM companion_conversation_turns ORDER BY created_at DESC LIMIT 8").fetchall()][::-1]
        memories = [dict(zip(["memory_type", "content", "importance"], row))
                    for row in snapshot.execute("SELECT memory_type,content,importance FROM companion_memories WHERE do_not_mention=0 ORDER BY importance DESC,created_at DESC LIMIT 8").fetchall()]
        loops = [dict(zip(["title", "status", "expected_followup"], row))
                 for row in snapshot.execute("SELECT title,status,expected_followup FROM companion_open_loops WHERE status NOT IN ('resolved','closed') ORDER BY updated_at DESC LIMIT 5").fetchall()]
        snapshot.close()
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
        mapping = json.loads((run_root / "snapshot" / "workbench-data" / "field-mapping.json").read_text(encoding="utf-8"))
        stable = {
            "persona": {
                "name": companion[1] if len(companion) > 1 else "溪语",
                "age": companion[2] if len(companion) > 2 else None,
                "roleTitle": companion[3] if len(companion) > 3 else None,
                "relationshipStage": companion[4] if len(companion) > 4 else None,
                "personaPromptSha256": sha(companion[7] if len(companion) > 7 else ""),
                "p1": "她是专业、有主见、活泼且略带狡黠的成年经营合作者，对这个用户有个人偏爱。她希望通过可靠判断和实际帮助获得信任，也希望形成工作之外的相互兴趣。长期追求影响她如何理解当前情境，不直接指定本轮主题、联系时间或媒介。工作时先把事实与行动交付清楚；个人互动拿出自己的选择、看法或小行动，让用户能调侃、反驳、参与。她可以主动争取注意，但不要求即时回复，不以空泛安慰和随时待命替代主体内容。",
            },
            "business": {"project": profile.get("project", {}), "venues": profile.get("venues", {}),
                        "fieldAliases": [x for x in mapping if x.get("code") in {"box_office_total", "sales_order_count", "reception_traffic", "daily.traffic", "daily.box_office"}]},
            "continuity": {"recentTurns": turns, "memories": memories, "openLoops": loops},
            "catalog": {"project": catalog.get("project"), "venues": catalog.get("venues"), "capabilities": catalog.get("capabilities")},
        }
        def system(mode, extra=""):
            decision = '输出严格JSON：{"operation":"new|continue|revise|suspend|complete","intention_id":"string","desired_change":"string","basis_refs":["string"],"action_type":"text|work_lookup|photo|none","strategy_reason":"string","expected_participation":"string","tool_args":{"projectId":"string","venueName":"string","date":"YYYY-MM-DD","question":"string"},"reconsider_condition":"string","messages":["string"]}，不要输出其它内容。'
            expression = "请用自然中文交付本轮结果，先满足用户实际问题；保留事实、日期、单位、门店和来源，不把旧资料冒充最新。"
            return stable["persona"]["p1"] + "\n\n你在隔离实验中，不能发送真实消息，也不能声称执行未完成动作。严格区分事实、用户原话、角色虚构生活和模型假设。\n真实业务背景：" + json.dumps(stable["business"], ensure_ascii=False) + "\n真实关系连续性：" + json.dumps(stable["continuity"], ensure_ascii=False) + "\n知识目录：" + json.dumps(stable["catalog"], ensure_ascii=False) + "\n" + (decision if mode == "decision" else expression) + "\n" + extra
        def call(label, prompt, messages):
            result = provider_call(provider, model, api_key, prompt, messages)
            trace.append({"stage": "provider_call", "label": label,
                          "request": {"systemHash": sha(prompt), "messages": messages},
                          "response": {k: v for k, v in result.items() if k != "error"}, "error": result.get("error")})
            return result
        trajectories = []
        query = "9月2号东坝店销售额是多少？"
        decision = call("I03-decision", system("decision"), [{"role": "user", "content": query}])
        parsed = extract_json(decision.get("text"))
        project_id = (catalog.get("project") or {}).get("id", "yuanqu-vr")
        body = {"actorId": "lab-owner", "projectId": project_id,
                "scope": {"projectId": project_id, "venueIds": ["DONGBA"], "venueNames": ["东坝"]},
                "query": {"topics": ["sales"], "metricIds": ["box_office_total"], "assetTypes": ["venue"],
                          "timeRange": "2026-09-02", "question": query, "interactionIntent": "lookup"},
                "limits": {"maxItems": 12, "maxCharacters": 8000}}
        retrieve_status, retrieve_payload = http_json(base + "/api/knowledge/retrieve", "POST", body, 45)
        tool = {"status": "complete" if retrieve_status == 200 else "unavailable",
                "httpStatus": retrieve_status, "result": retrieve_payload}
        final = call("I03-expression", system("expression", "本轮决策：" + json.dumps(parsed, ensure_ascii=False) + "\n工具真实返回：" + json.dumps(tool, ensure_ascii=False)[:24000] + "\n必须回答用户销售额问题；没有该精确日期就说明没有精确记录，不能把旧周数据冒充9月2日。"), [{"role": "user", "content": query}])
        sink.append({"target": "sink://ideal-lab", "text": final.get("text", ""), "intentionId": parsed.get("intention_id") if isinstance(parsed, dict) else None})
        trajectories.append({"id": "I03", "input": query, "decision": parsed, "tool": tool, "final": final.get("text", ""), "sink": sink[-1]})
        opportunity = "虚拟时钟机会：用户今天没有主动发消息，允许一次低负担主动联系。"
        decision = call("I01-decision", system("decision"), [{"role": "user", "content": opportunity}])
        parsed = extract_json(decision.get("text"))
        final = call("I01-expression", system("expression", "这是一次主动联系。决策：" + json.dumps(parsed, ensure_ascii=False) + "。必须有主体内容和明确可接位置，不得声称刚看见不存在的事件，不要索取业务背景中已经存在的信息。"), [{"role": "user", "content": opportunity}])
        sink.append({"target": "sink://ideal-lab", "text": final.get("text", ""), "intentionId": parsed.get("intention_id") if isinstance(parsed, dict) else None})
        trajectories.append({"id": "I01", "input": opportunity, "decision": parsed, "final": final.get("text", ""), "sink": sink[-1]})
        result = {"status": "completed", "startedAt": started, "provider": provider, "model": model or None,
                  "contextEvidence": {"project": (catalog.get("project") or {}).get("name"),
                                      "venues": [v.get("name") for v in catalog.get("venues", []) if isinstance(v, dict)],
                                      "catalogStatus": catalog_probe["status"], "companionPresent": bool(companion),
                                      "recentTurnCount": len(turns), "memoryCount": len(memories), "openLoopCount": len(loops)},
                  "trajectories": trajectories, "trace": trace, "sink": sink,
                  "limitations": ["仅E3最小冒烟：I01/I03；未运行固定24族、留出、媒体、7日连续性。",
                                  "真实模型输出是证据，不代表通过；需按规范执行完整套件。",
                                  "工作台使用隔离副本；无飞书写回、真实Bot投递。"]}
    except Exception as exc:
        result = {"status": "failed", "startedAt": started, "provider": provider, "error": str(exc), "trace": trace, "sink": sink}
    finally:
        if proc:
            proc.terminate()
            try: proc.wait(timeout=5)
            except Exception: proc.kill()
    (run_root / "smoke-result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": result["status"], "provider": result.get("provider"),
                      "trajectories": [{"id": x["id"], "hasDecision": bool(x.get("decision")),
                                        "finalChars": len(x.get("final", "")),
                                        "sink": x.get("sink", {}).get("target")}
                                       for x in result.get("trajectories", [])],
                      "providerCalls": len(result.get("trace", [])),
                      "output": str(run_root / "smoke-result.json")}, ensure_ascii=False))
    if result["status"] != "completed": raise SystemExit(1)

if __name__ == "__main__":
    main()

