import assert from 'node:assert/strict';
import test from 'node:test';
import { createReadingTimeCounter } from './read-time';

test('excludes hidden time and keeps previous sessions', () => {
  let clock = 1000;
  const timer = createReadingTimeCounter(60, () => clock);
  clock = 4000;
  timer.pause();
  clock = 94000;
  assert.equal(timer.seconds(), 63);
  timer.resume();
  clock = 99000;
  assert.equal(timer.seconds(), 68);
});
