/** Bound epub.js tasks that may emit an error without settling their promise. */
export function waitForReading<T>(task: Promise<T>, signal: AbortSignal, stage: string, timeout = 30000): Promise<T> {
  let timer: ReturnType<typeof setTimeout>;
  let abort = () => {};
  const pending = new Promise<T>((resolve, reject) => {
    abort = () => reject(new DOMException('阅读已取消', 'AbortError'));
    timer = setTimeout(() => reject(new Error(`${stage}超时，请重试；本机书籍与进度已保留。`)), timeout);
    signal.addEventListener('abort', abort, { once: true });
    task.then(resolve, reject);
    if (signal.aborted) abort();
  });
  return pending.finally(() => {
    clearTimeout(timer);
    signal.removeEventListener('abort', abort);
  });
}
