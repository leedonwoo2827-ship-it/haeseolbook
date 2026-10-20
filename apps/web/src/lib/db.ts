import { openDB, type DBSchema, type IDBPDatabase } from 'idb';
import type { BookManifest, InkPage } from '@hsb/shared';

/** 로컬 우선 저장: 필기는 여기 먼저 쓰고 sync.ts 가 서버로 올린다 */
export interface LocalInk {
  key: string; // `${bookId}:${pageId}`
  bookId: string;
  pageId: string;
  ink: InkPage;
  baseRev: number; // 마지막으로 서버와 맞춘 리비전
  dirty: boolean;
  deletedIds: string[]; // 서버본과 병합할 때 되살아나지 않게 할 삭제 획
  updatedAt: number;
}

interface HsbDB extends DBSchema {
  ink: { key: string; value: LocalInk; indexes: { byBook: string } };
  manifests: { key: string; value: { bookId: string; manifest: BookManifest; savedAt: number } };
  meta: { key: string; value: { key: string; value: string } };
}

let dbp: Promise<IDBPDatabase<HsbDB>> | null = null;

function db() {
  dbp ??= openDB<HsbDB>('haeseolbook', 1, {
    upgrade(d) {
      d.createObjectStore('ink', { keyPath: 'key' }).createIndex('byBook', 'bookId');
      d.createObjectStore('manifests', { keyPath: 'bookId' });
      d.createObjectStore('meta', { keyPath: 'key' });
    },
  });
  return dbp;
}

export const inkKey = (bookId: string, pageId: string) => `${bookId}:${pageId}`;

export async function getBookInk(bookId: string): Promise<LocalInk[]> {
  return (await db()).getAllFromIndex('ink', 'byBook', bookId);
}

export async function getInk(bookId: string, pageId: string): Promise<LocalInk | undefined> {
  return (await db()).get('ink', inkKey(bookId, pageId));
}

export async function putInk(v: LocalInk): Promise<void> {
  await (await db()).put('ink', v);
}

export async function saveManifest(m: BookManifest) {
  await (await db()).put('manifests', { bookId: m.book.id, manifest: m, savedAt: Date.now() });
}

export async function loadManifest(bookId: string): Promise<BookManifest | undefined> {
  return (await (await db()).get('manifests', bookId))?.manifest;
}

export async function getMeta(key: string): Promise<string | undefined> {
  return (await (await db()).get('meta', key))?.value;
}

export async function setMeta(key: string, value: string) {
  await (await db()).put('meta', { key, value });
}
