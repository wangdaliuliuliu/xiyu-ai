/**
 * 工作台窄范围的“慢任务先确认”封装。
 *
 * 这不是通用消息队列，也不改变现有 coalesce / photo 异步链路：
 * 只有明确要求重新核对工作数据的请求才会使用它。操作很快时不会发
 * 额外消息；操作超过阈值时先发一次确认，原 Promise 继续完成并由调用方
 * 发送最终结果。
 */

const activeTasks = new Map();

export function isDeferredWorkTaskActive(key) {
  return Boolean(key && activeTasks.has(String(key)));
}

export function activeDeferredWorkTaskCount() {
  return activeTasks.size;
}

/**
 * @returns {Promise<{ value: any, deferred: boolean, ackError: Error|null, elapsedMs: number }>}
 */
export async function runDeferredWorkTask({ key, operation, onDeferred, delayMs = 2500 } = {}) {
  const taskKey = String(key || '').trim();
  if (!taskKey) throw new Error('deferred work task requires a key');
  if (typeof operation !== 'function') throw new Error('deferred work task requires an operation');

  // 正常情况下由 inflightUsers 避免同一用户并发；这里仍保留一个窄锁，
  // 防止未来其他入口重复触发同一门店的刷新。
  const previous = activeTasks.get(taskKey);
  if (previous) return previous.promise;

  const startedAt = Date.now();
  let settled = false;
  let deferred = false;
  let ackError = null;
  let ackPromise = null;

  const promise = (async () => {
    const timer = setTimeout(() => {
      if (settled) return;
      deferred = true;
      ackPromise = Promise.resolve()
        .then(() => onDeferred?.({ elapsedMs: Date.now() - startedAt, key: taskKey }))
        .catch(error => { ackError = error; });
    }, Math.max(0, Number(delayMs) || 0));

    let value;
    let operationError = null;
    try {
      value = await operation();
    } catch (error) {
      operationError = error;
    } finally {
      settled = true;
      clearTimeout(timer);
    }

    // 若确认回调已经启动，必须等它发完再让调用方生成最终结果，
    // 避免出现最终答复先于“我正在核对”的消息。
    if (ackPromise) await ackPromise;
    if (operationError) throw operationError;
    return { value, deferred, ackError, elapsedMs: Date.now() - startedAt };
  })();

  activeTasks.set(taskKey, { promise, startedAt });
  try {
    return await promise;
  } finally {
    if (activeTasks.get(taskKey)?.promise === promise) activeTasks.delete(taskKey);
  }
}

