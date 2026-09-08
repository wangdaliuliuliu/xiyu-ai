import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const TARGET = JSON.parse(fs.readFileSync(path.join(ROOT, 'data', 'feishu-target.json'), 'utf8'));
const ENV_PATH = path.join(ROOT, 'backend', '.env');
for (const line of fs.readFileSync(ENV_PATH, 'utf8').split(/\r?\n/)) {
  const match = line.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*?)\s*$/);
  if (match && !process.env[match[1]]) process.env[match[1]] = match[2].replace(/^['"]|['"]$/g, '');
}

const API_BASE = (process.env.FEISHU_API_BASE || 'https://open.feishu.cn/open-apis').replace(/\/$/, '');
const APP_ID = process.env.FEISHU_APP_ID || '';
const APP_SECRET = process.env.FEISHU_APP_SECRET || '';
const TOKEN = process.env.FEISHU_SPREADSHEET_TOKEN || TARGET.workbook.token;
const PERIOD_ID = '2099-12-14_2099-12-20';
const SNAPSHOT_DATE = '2099-12-20';
const VENUE = '东坝';
const MARKER = 'E2E测试记录';
const SNAPSHOT_PATH = path.join(ROOT, 'backend', '.e2e-feishu-snapshot-2099-12-14.json');
const MAX_ROWS = 500;
const SECTION_COUNTS = {
  weekly_core: 1,
  channel_metric: 7,
  daily_traffic: 7,
  daily_box_office: 7,
  card_metric: 2,
  card_cumulative_snapshot: 1,
  playback_metric: 2
};

let accessToken = '';

async function tenantAccessToken() {
  if (accessToken) return accessToken;
  const response = await fetch(`${API_BASE}/auth/v3/tenant_access_token/internal`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ app_id: APP_ID, app_secret: APP_SECRET })
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok || body.code !== 0 || !body.tenant_access_token) throw new Error(`获取飞书令牌失败：${body.msg || response.status}`);
  accessToken = body.tenant_access_token;
  return accessToken;
}

async function feishuRequest(method, endpoint, body) {
  const response = await fetch(`${API_BASE}${endpoint}`, {
    method,
    headers: { Authorization: `Bearer ${await tenantAccessToken()}`, 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body)
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok || (data.code !== undefined && data.code !== 0)) throw new Error(`飞书 API 失败：${data.msg || response.status}（${data.code ?? response.status}）`);
  return data;
}

function rangeEndpoint(sheetId, formula = false) {
  const range = `${sheetId}!A1:Z${MAX_ROWS}`;
  const query = formula ? '?valueRenderOption=Formula' : '';
  return `/sheets/v2/spreadsheets/${encodeURIComponent(TOKEN)}/values/${encodeURIComponent(range)}${query}`;
}

async function readValues(sheetId, formula = false) {
  const data = await feishuRequest('GET', rangeEndpoint(sheetId, formula));
  return data?.data?.valueRange?.values || [];
}

function rowAt(values, rowNumber, width) {
  const row = values[rowNumber - 1] || [];
  return Array.from({ length: width }, (_, i) => row[i] ?? null);
}

function isBlankCell(cell) {
  if (cell === null || cell === undefined || cell === '') return true;
  if (typeof cell === 'object') {
    const text = cell.text ?? cell.value ?? cell.formula;
    return text === null || text === undefined || text === '';
  }
  return false;
}

function hasFormula(cell) {
  if (typeof cell === 'string') return cell.startsWith('=');
  if (!cell || typeof cell !== 'object') return false;
  return cell.type === 'formula' || String(cell.formula ?? cell.text ?? '').startsWith('=');
}

function comparableCell(cell) {
  return isBlankCell(cell) ? null : cell;
}

function sameRow(left, right) {
  return JSON.stringify(left.map(comparableCell)) === JSON.stringify(right.map(comparableCell));
}

async function snapshot() {
  if (!APP_ID || !APP_SECRET) throw new Error('缺少飞书应用配置');
  const sheets = [];
  for (const [section, count] of Object.entries(SECTION_COUNTS)) {
    const config = TARGET.sheets[section];
    const values = await readValues(config.sheetId, false);
    let formulaValues;
    let formulaRead = true;
    try { formulaValues = await readValues(config.sheetId, true); }
    catch { formulaRead = false; formulaValues = values; }
    const headers = values[0] || formulaValues[0] || [];
    const width = Math.max(headers.length, 1);
    const reserved = new Set();
    const candidates = [];
    const existingMax = Math.max(values.length, formulaValues.length, 1);
    for (let n = 0; n < count; n++) {
      let rowNumber = 2;
      while (rowNumber <= MAX_ROWS) {
        const normalRow = rowAt(values, rowNumber, width);
        const formulaRow = rowAt(formulaValues, rowNumber, width);
        if (!reserved.has(rowNumber) && normalRow.every(isBlankCell) && formulaRow.every(isBlankCell)) break;
        rowNumber++;
      }
      if (rowNumber > MAX_ROWS) rowNumber = existingMax + n + 1;
      reserved.add(rowNumber);
      const normalRow = rowAt(values, rowNumber, width);
      const formulaRow = rowAt(formulaValues, rowNumber, width);
      candidates.push({ rowNumber, values: normalRow, formulaValues: formulaRow, formulas: formulaRow.map((cell, index) => hasFormula(cell) ? index : -1).filter(index => index >= 0) });
    }
    sheets.push({ section, sheetId: config.sheetId, sheetName: config.sheetName, headers, width, formulaRead, candidates });
  }
  const payload = { createdAt: new Date().toISOString(), workbook: TARGET.workbook.title, periodId: PERIOD_ID, snapshotDate: SNAPSHOT_DATE, venue: VENUE, marker: MARKER, sheets };
  fs.writeFileSync(SNAPSHOT_PATH, JSON.stringify(payload, null, 2), 'utf8');
  console.log(JSON.stringify({ ok: true, snapshotPath: SNAPSHOT_PATH, sheets: sheets.map(sheet => ({ section: sheet.section, sheetName: sheet.sheetName, rows: sheet.candidates.map(row => row.rowNumber), formulaRead: sheet.formulaRead, originalFormulaCells: sheet.candidates.reduce((n, row) => n + row.formulas.length, 0) })) }, null, 2));
}

function matchesTestRow(headers, row) {
  const index = Object.fromEntries(headers.map((header, i) => [String(header || '').trim(), i]));
  const note = String(row[index['备注']] ?? '');
  const venue = String(row[index['门店名称']] ?? '');
  const period = String(row[index['周期ID']] ?? '');
  const dateValue = row[index['快照日期']];
  const date = String(dateValue ?? '');
  const snapshotSerial = Math.round((Date.parse(`${SNAPSHOT_DATE}T00:00:00Z`) - Date.parse('1899-12-30T00:00:00Z')) / 86400000);
  const dateMatches = date === SNAPSHOT_DATE || Number(dateValue) === snapshotSerial;
  return note.includes(MARKER) && venue === VENUE && (period === PERIOD_ID || dateMatches);
}

async function restore() {
  if (!fs.existsSync(SNAPSHOT_PATH)) throw new Error(`找不到写入前快照：${SNAPSHOT_PATH}`);
  const snapshotData = JSON.parse(fs.readFileSync(SNAPSHOT_PATH, 'utf8'));
  const restored = [];
  for (const sheet of snapshotData.sheets) {
    const currentValues = await readValues(sheet.sheetId, false);
    const currentFormulaValues = sheet.formulaRead ? await readValues(sheet.sheetId, true) : currentValues;
    for (const candidate of sheet.candidates) {
      const currentRow = rowAt(currentValues, candidate.rowNumber, sheet.width);
      const currentFormulaRow = rowAt(currentFormulaValues, candidate.rowNumber, sheet.width);
      const alreadyRestored = sameRow(currentRow, candidate.values) && sameRow(currentFormulaRow, candidate.formulaValues || candidate.values);
      if (alreadyRestored) {
        restored.push({ sheet: sheet.sheetName, rowNumber: candidate.rowNumber, status: 'already_restored' });
        continue;
      }
      if (!matchesTestRow(sheet.headers, currentRow)) throw new Error(`${sheet.sheetName} 第 ${candidate.rowNumber} 行不符合测试标记，停止恢复`);
      const restoreValues = candidate.formulaValues || candidate.values;
      const end = columnLetter(sheet.width);
      await feishuRequest('PUT', `/sheets/v2/spreadsheets/${encodeURIComponent(TOKEN)}/values`, { valueRange: { range: `${sheet.sheetId}!A${candidate.rowNumber}:${end}${candidate.rowNumber}`, values: [restoreValues] } });
      restored.push({ sheet: sheet.sheetName, rowNumber: candidate.rowNumber, status: 'restored' });
    }
    const verifyNormal = await readValues(sheet.sheetId, false);
    const verifyFormula = sheet.formulaRead ? await readValues(sheet.sheetId, true) : verifyNormal;
    for (const candidate of sheet.candidates) {
      const normalOk = sameRow(rowAt(verifyNormal, candidate.rowNumber, sheet.width), candidate.values);
      const formulaOk = sameRow(rowAt(verifyFormula, candidate.rowNumber, sheet.width), candidate.formulaValues || candidate.values);
      if (!normalOk || !formulaOk) throw new Error(`${sheet.sheetName} 第 ${candidate.rowNumber} 行恢复后校验失败`);
    }
  }
  console.log(JSON.stringify({ ok: true, restored, verified: true, formulasVerified: snapshotData.sheets.every(sheet => sheet.formulaRead) }, null, 2));
}

async function inspect() {
  if (!fs.existsSync(SNAPSHOT_PATH)) throw new Error(`找不到写入前快照：${SNAPSHOT_PATH}`);
  const snapshotData = JSON.parse(fs.readFileSync(SNAPSHOT_PATH, 'utf8'));
  const differences = [];
  for (const sheet of snapshotData.sheets) {
    const values = await readValues(sheet.sheetId, false);
    const formulaValues = sheet.formulaRead ? await readValues(sheet.sheetId, true) : values;
    for (const candidate of sheet.candidates) {
      const current = rowAt(values, candidate.rowNumber, sheet.width);
      const currentFormula = rowAt(formulaValues, candidate.rowNumber, sheet.width);
      if (!sameRow(current, candidate.values) || !sameRow(currentFormula, candidate.formulaValues || candidate.values)) {
        differences.push({ sheet: sheet.sheetName, rowNumber: candidate.rowNumber, headers: sheet.headers, current, currentFormula, expected: candidate.values, expectedFormula: candidate.formulaValues });
      }
    }
  }
  console.log(JSON.stringify({ ok: true, differences }, null, 2));
}

function columnLetter(n) {
  let out = '';
  for (let x = n; x > 0; x = Math.floor((x - 1) / 26)) out = String.fromCharCode(65 + ((x - 1) % 26)) + out;
  return out;
}

const command = process.argv[2];
if (command === 'snapshot') await snapshot();
else if (command === 'restore') await restore();
else if (command === 'inspect') await inspect();
else throw new Error('用法：node backend/e2e-feishu-guard.mjs snapshot|restore|inspect');
