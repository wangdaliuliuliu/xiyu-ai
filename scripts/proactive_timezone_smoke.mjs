import assert from 'node:assert/strict';
import { computeTimeBaseScore, selectProactiveTrigger, shanghaiClock } from '../src/proactive_engine.mjs';

const utcLateNight = new Date('2026-09-06T23:30:00.000Z'); // 上海次日 07:30
assert.deepEqual(shanghaiClock(utcLateNight), { hour: 7, minute: 30 });
assert.equal(computeTimeBaseScore(utcLateNight), 70);
assert.equal(selectProactiveTrigger({ id: -1 }, { now: utcLateNight, motivation: 60 }), 'morning_greeting');

const utcAfternoon = new Date('2026-09-06T15:30:00.000Z'); // 上海 23:30
assert.deepEqual(shanghaiClock(utcAfternoon), { hour: 23, minute: 30 });
assert.equal(computeTimeBaseScore(utcAfternoon), 5);
assert.equal(selectProactiveTrigger({ id: -1 }, { now: utcAfternoon, motivation: 60 }), 'goodnight');

console.log(JSON.stringify({ status: 'passed', checks: ['UTC host maps to Shanghai morning', 'UTC host maps to Shanghai night'] }));
