import { test } from 'node:test';
import assert from 'node:assert/strict';
import { segmentAt, cueAt, inkChecksum, mergeInk, guessDeviceType, Stroke, VideoSegment, InkPage } from './index';

const seg = (quizId: string, startSec: number, endSec: number): VideoSegment => ({ quizId, youtubeId: 'abcdefghijk', startSec, endSec, cues: [] });
const stroke = (id: string, createdAt: number): Stroke => ({
  id, tool: 'pen', color: '#111111', size: 0.003, points: [[0.1, 0.1, 0.5]], videoTime: null, createdAt,
});
const page = (strokes: Stroke[]): InkPage => ({ version: 1, pageId: 'p1', strokes });

test('segmentAt picks the covering segment', () => {
  const segs = [seg('q1', 0, 60), seg('q2', 60, 120)];
  assert.equal(segmentAt(segs, 59.9)?.quizId, 'q1');
  assert.equal(segmentAt(segs, 60)?.quizId, 'q2');
  assert.equal(segmentAt(segs, 120), null);
});

test('segmentAt prefers the later start on overlap', () => {
  assert.equal(segmentAt([seg('a', 0, 100), seg('b', 50, 70)], 55)?.quizId, 'b');
});

test('VideoSegment rejects inverted ranges', () => {
  assert.equal(VideoSegment.safeParse(seg('q', 10, 5)).success, false);
});

test('inkChecksum is stable and order sensitive', () => {
  const a = page([stroke('s1', 1), stroke('s2', 2)]);
  assert.equal(inkChecksum(a), inkChecksum(structuredClone(a)));
  assert.notEqual(inkChecksum(a), inkChecksum(page([stroke('s2', 2), stroke('s1', 1)])));
});

test('mergeInk unions by id, sorts by time, applies deletions', () => {
  const merged = mergeInk(page([stroke('b', 2), stroke('c', 3)]), page([stroke('a', 1), stroke('b', 2)]), new Set(['c']));
  assert.deepEqual(merged.strokes.map((s) => s.id), ['a', 'b']);
});

test('cueAt interpolates within a page and holds across page changes', () => {
  const cues = [
    { t: 10, pageNo: 1, x: 0, y: 0 },
    { t: 20, pageNo: 1, x: 1, y: 0.5 },
    { t: 30, pageNo: 2, x: 0.2, y: 0.2 },
  ];
  assert.equal(cueAt(cues, 5), null);
  assert.deepEqual(cueAt(cues, 15), { t: 15, pageNo: 1, x: 0.5, y: 0.25 });
  assert.equal(cueAt(cues, 25)?.pageNo, 1);
  assert.equal(cueAt(cues, 99)?.pageNo, 2);
});

test('guessDeviceType', () => {
  assert.equal(guessDeviceType('Mozilla/5.0 (Windows NT 10.0; Win64; x64)', 1080), 'pc');
  assert.equal(guessDeviceType('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0) Mobile', 390), 'phone');
  assert.equal(guessDeviceType('Mozilla/5.0 (Linux; Android 14; SM-X910) Safari', 1200), 'tablet');
});
