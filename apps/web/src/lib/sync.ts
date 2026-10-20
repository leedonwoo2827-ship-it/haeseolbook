import { INK_FORMAT_VERSION, inkChecksum, mergeInk, type InkPage, type Stroke } from '@hsb/shared';
import { ApiError, pullInk, pushInk } from './api';
import { getBookInk, getInk, getMeta, inkKey, putInk, setMeta, type LocalInk } from './db';

const EMPTY: Stroke[] = [];

export type SyncState = 'idle' | 'saving' | 'saved' | 'offline' | 'error';

/**
 * 필기 동기화 엔진 (교재 1권 단위).
 * - 편집은 IndexedDB 에 즉시 저장(dirty) → 디바운스 후 서버로 push
 * - 서버 rev 가 앞서 있으면(다른 기기에서 수정) mergeInk 로 합친 뒤 재시도
 * - 주기적 pull 로 다른 기기의 필기를 받아온다
 */
export class InkSync {
  private pages = new Map<string, LocalInk>();
  private timer: number | null = null;
  private pollTimer: number | null = null;
  private pushing = false;
  private listeners = new Set<() => void>();
  state: SyncState = 'idle';

  constructor(private readonly bookId: string) {}

  async start() {
    for (const p of await getBookInk(this.bookId)) this.pages.set(p.pageId, p);
    this.emit();
    await this.pull();
    this.schedule(0);
    this.pollTimer = window.setInterval(() => void this.pull(), 30_000);
    window.addEventListener('online', this.onOnline);
  }

  stop() {
    if (this.timer) clearTimeout(this.timer);
    if (this.pollTimer) clearInterval(this.pollTimer);
    window.removeEventListener('online', this.onOnline);
    void this.flush();
  }

  subscribe(fn: () => void): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  strokes(pageId: string): Stroke[] {
    return this.pages.get(pageId)?.ink.strokes ?? EMPTY;
  }

  allStrokes(): { pageId: string; stroke: Stroke }[] {
    return [...this.pages.values()].flatMap((p) => p.ink.strokes.map((stroke) => ({ pageId: p.pageId, stroke })));
  }

  async setStrokes(pageId: string, strokes: Stroke[], removedIds: string[] = []) {
    const cur = this.pages.get(pageId) ?? (await getInk(this.bookId, pageId));
    const deleted = new Set([...(cur?.deletedIds ?? []), ...removedIds]);
    for (const s of strokes) deleted.delete(s.id);
    const next: LocalInk = {
      key: inkKey(this.bookId, pageId), bookId: this.bookId, pageId,
      ink: { version: INK_FORMAT_VERSION, pageId, strokes }, baseRev: cur?.baseRev ?? 0,
      dirty: true, deletedIds: [...deleted].slice(-2000), updatedAt: Date.now(),
    };
    this.pages.set(pageId, next);
    this.emit();
    await putInk(next);
    this.schedule(1500);
  }

  private onOnline = () => this.schedule(0);

  private schedule(ms: number) {
    if (this.timer) clearTimeout(this.timer);
    this.timer = window.setTimeout(() => void this.flush(), ms);
  }

  private setState(s: SyncState) {
    if (this.state !== s) {
      this.state = s;
      this.emit();
    }
  }

  private emit() {
    this.listeners.forEach((l) => l());
  }

  async pull() {
    if (!navigator.onLine) return this.setState('offline');
    try {
      const since = await getMeta(`pulled:${this.bookId}`);
      const rows = await pullInk(this.bookId, since);
      let latest = since ?? '';
      for (const r of rows) {
        if (r.updatedAt > latest) latest = r.updatedAt;
        const local = this.pages.get(r.pageId);
        if (local && local.baseRev >= r.rev) continue;
        const ink: InkPage = local?.dirty ? mergeInk(local.ink, r.ink, new Set(local.deletedIds)) : r.ink;
        const next: LocalInk = {
          key: inkKey(this.bookId, r.pageId), bookId: this.bookId, pageId: r.pageId, ink, baseRev: r.rev,
          dirty: !!local?.dirty, deletedIds: local?.deletedIds ?? [], updatedAt: Date.now(),
        };
        this.pages.set(r.pageId, next);
        await putInk(next);
      }
      if (latest) await setMeta(`pulled:${this.bookId}`, latest);
      if (rows.length) this.emit();
    } catch (e) {
      this.setState(e instanceof ApiError ? 'error' : 'offline');
    }
  }

  async flush() {
    if (this.pushing) return;
    const dirty = [...this.pages.values()].filter((p) => p.dirty);
    if (!dirty.length) return this.setState(this.state === 'saving' ? 'saved' : this.state);
    if (!navigator.onLine) return this.setState('offline');
    this.pushing = true;
    this.setState('saving');
    try {
      for (const page of dirty) await this.pushPage(page);
      this.setState('saved');
    } catch (e) {
      this.setState(e instanceof ApiError && e.status !== 401 ? 'error' : 'offline');
      this.schedule(15_000);
    } finally {
      this.pushing = false;
    }
  }

  private async pushPage(page: LocalInk, attempt = 0): Promise<void> {
    const res = await pushInk({ bookId: this.bookId, pageId: page.pageId, baseRev: page.baseRev, ink: page.ink, checksum: inkChecksum(page.ink) });
    const current = this.pages.get(page.pageId);
    if (res.status === 'ok') {
      // push 중에 새로 그린 획이 있으면 dirty 를 유지한다
      const changed = current && current.updatedAt !== page.updatedAt;
      const next: LocalInk = { ...(current ?? page), baseRev: res.rev, dirty: !!changed, deletedIds: changed ? current!.deletedIds : [] };
      this.pages.set(page.pageId, next);
      await putInk(next);
      return;
    }
    if (attempt >= 3) throw new ApiError(409, '필기 동기화 충돌이 반복됩니다');
    const base = current ?? page;
    const merged: LocalInk = {
      ...base, ink: mergeInk(base.ink, res.server.ink, new Set(base.deletedIds)), baseRev: res.server.rev, dirty: true, updatedAt: Date.now(),
    };
    this.pages.set(page.pageId, merged);
    await putInk(merged);
    this.emit();
    return this.pushPage(merged, attempt + 1);
  }
}
