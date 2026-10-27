/** Count only time while the reader is visible, even across background tabs. */
export function createReadingTimeCounter(initialSeconds = 0, now = Date.now) {
  let elapsedMs = Math.max(0, initialSeconds) * 1000;
  let lastTick = now();
  let active = true;
  const settle = () => {
    const next = now();
    if (active) elapsedMs += Math.max(0, next - lastTick);
    lastTick = next;
  };
  return {
    pause() {
      settle();
      active = false;
    },
    resume() {
      settle();
      active = true;
    },
    seconds() {
      settle();
      return Math.floor(elapsedMs / 1000);
    },
  };
}
