import { uuid } from './uuid';
import { guessDeviceType, type BookManifest, type BookSummary, type DeviceType, type InkPage, type InkPushResponse } from '@hsb/shared';

export const API_URL = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? '/api';

const REFRESH_KEY = 'hsb.refresh';
const DEVICE_KEY = 'hsb.device';

export class ApiError extends Error {
  constructor(public status: number, message: string, public code?: string) {
    super(message);
  }
}

// ---------- 기기 ----------

export function deviceId(): string {
  let id = safeGet(DEVICE_KEY);
  if (!id) {
    id = uuid();
    safeSet(DEVICE_KEY, id);
  }
  return id;
}

export function deviceType(): DeviceType {
  return guessDeviceType(navigator.userAgent, Math.min(screen.width, screen.height));
}

/** 앱 셸(Tauri/Capacitor) 안에서 실행 중인지. 셸은 출판사 사이트를 그대로 띄우고 UA 에 표식을 붙인다 */
export function inAppShell(): boolean {
  return /HaeseolbookApp\//.test(navigator.userAgent);
}

type ShellWindow = Window & {
  __TAURI_INTERNALS__?: { invoke: (cmd: string, args: object) => Promise<unknown> };
  Capacitor?: { Plugins?: { Browser?: { open: (o: { url: string }) => Promise<void> } } };
};

/** 시스템 브라우저로 열기 (구글·카카오는 앱 내 웹뷰 로그인을 막으므로). 셸이 아니면 그냥 이동 */
export async function openExternal(url: string): Promise<void> {
  const w = window as ShellWindow;
  try {
    if (w.__TAURI_INTERNALS__) return void (await w.__TAURI_INTERNALS__.invoke('plugin:opener|open_url', { url }));
    if (w.Capacitor?.Plugins?.Browser) return await w.Capacitor.Plugins.Browser.open({ url });
  } catch { /* 셸 기능이 없으면 아래로 */ }
  location.href = url;
}

function deviceLabel(): string {
  const ua = navigator.userAgent;
  const os = /Windows/.test(ua) ? 'Windows' : /Android/.test(ua) ? 'Android' : /iPhone|iPad/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1) ? 'iOS/iPadOS'
    : /Mac OS X/.test(ua) ? 'macOS' : /Linux/.test(ua) ? 'Linux' : '기타';
  return `${os} · ${inAppShell() ? '앱' : 'PWA/브라우저'}`;
}

function deviceBody() {
  return { deviceId: deviceId(), deviceType: deviceType(), label: deviceLabel() };
}

// ---------- 토큰 ----------

interface Tokens { accessToken: string; refreshToken: string; expiresIn: number; replacedDevices: string[] }

let access: { token: string; exp: number } | null = null;
let refreshing: Promise<boolean> | null = null;
const listeners = new Set<(loggedIn: boolean, reason?: string) => void>();

export function onAuthChange(fn: (loggedIn: boolean, reason?: string) => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

function setTokens(t: Tokens) {
  access = { token: t.accessToken, exp: Date.now() + (t.expiresIn - 30) * 1000 };
  safeSet(REFRESH_KEY, t.refreshToken);
  listeners.forEach((l) => l(true));
}

export function clearSession(reason?: string) {
  access = null;
  safeDel(REFRESH_KEY);
  listeners.forEach((l) => l(false, reason));
}

export function hasSession(): boolean {
  return !!safeGet(REFRESH_KEY);
}

async function refresh(): Promise<boolean> {
  const rt = safeGet(REFRESH_KEY);
  if (!rt) return false;
  refreshing ??= (async () => {
    try {
      const res = await fetch(`${API_URL}/auth/refresh`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ refreshToken: rt }) });
      if (res.status === 401) {
        const b = await res.json().catch(() => ({}));
        clearSession(b.message);
        return false;
      }
      if (!res.ok) return false; // 서버 일시 오류·오프라인: 세션은 유지
      setTokens(await res.json());
      return true;
    } catch {
      return false;
    } finally {
      refreshing = null;
    }
  })();
  return refreshing;
}

export async function api<T>(path: string, init: RequestInit = {}, auth = true): Promise<T> {
  const doFetch = async () => {
    const headers = new Headers(init.headers);
    if (init.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
    if (auth && access) headers.set('Authorization', `Bearer ${access.token}`);
    return fetch(`${API_URL}${path}`, { ...init, headers });
  };
  if (auth && (!access || access.exp < Date.now()) && hasSession()) await refresh();
  let res = await doFetch();
  if (res.status === 401 && auth) {
    const b = await res.clone().json().catch(() => ({}));
    if (b.code === 'device_replaced') {
      clearSession(b.message);
      throw new ApiError(401, b.message, b.code);
    }
    if (await refresh()) res = await doFetch();
  }
  if (!res.ok) {
    const b = await res.json().catch(() => ({}));
    throw new ApiError(res.status, b.message ?? `요청 실패 (${res.status})`, b.code);
  }
  return res.status === 204 ? (undefined as T) : res.json();
}

// ---------- 로그인 ----------

export interface Providers { g5: boolean; dev: boolean; google: boolean; kakao: boolean }

export const getProviders = () => api<Providers>('/auth/providers', {}, false);

export async function devLogin(email: string, name?: string) {
  setTokens(await api<Tokens>('/auth/dev-login', { method: 'POST', body: JSON.stringify({ email, name, ...deviceBody() }) }, false));
}

export async function exchangeCode(code: string): Promise<string[]> {
  const t = await api<Tokens>('/auth/exchange', { method: 'POST', body: JSON.stringify({ code, ...deviceBody() }) }, false);
  setTokens(t);
  return t.replacedDevices;
}

/**
 * 사이트 회원(g5)·구글·카카오 로그인 시작 URL.
 * g5 는 같은 사이트라 앱 셸 웹뷰 안에서 그대로 진행(target=web).
 * 구글·카카오는 앱 셸이면 시스템 브라우저에서 진행하고 딥링크로 돌아온다(target=app).
 */
export function loginUrl(provider: 'g5' | 'google' | 'kakao'): string {
  const target = provider !== 'g5' && inAppShell() ? 'app' : 'web';
  const abs = new URL(API_URL, location.href).toString().replace(/\/$/, '');
  return provider === 'g5' ? `${abs}/auth/g5/start?target=${target}` : `${abs}/auth/oauth/${provider}/start?target=${target}`;
}

export async function logout() {
  try {
    await api('/auth/logout', { method: 'POST' });
  } finally {
    clearSession();
  }
}

export interface Me {
  user: { id: string; email: string; name: string | null; provider: string };
  deviceId: string;
  devices: { id: string; type: DeviceType; label: string | null; lastSeenAt: string }[];
}
export const getMe = () => api<Me>('/auth/me');
export const removeDevice = (id: string) => api<void>(`/auth/devices/${encodeURIComponent(id)}`, { method: 'DELETE' });

// ---------- 교재 / 학습 ----------

export type BookItem = BookSummary & { videoCount?: number };
export const listBooks = () => api<BookItem[]>('/books', {}, hasSession());
export const getManifest = (id: string) => api<BookManifest>(`/books/${encodeURIComponent(id)}/manifest`);

export interface Attempt { quizId: string; chosen: number; correct: boolean; tries: number; everWrong: boolean }
export const listAttempts = (bookId: string) => api<Attempt[]>(`/books/${encodeURIComponent(bookId)}/attempts`);
export const submitAttempt = (bookId: string, quizId: string, chosen: number) =>
  api<{ correct: boolean; answer: number }>(`/books/${encodeURIComponent(bookId)}/attempts`, { method: 'POST', body: JSON.stringify({ quizId, chosen }) });

export interface ServerInk { pageId: string; rev: number; checksum: string; ink: InkPage; updatedAt: string }
export const pullInk = (bookId: string, updatedAfter?: string) =>
  api<ServerInk[]>(`/ink/${encodeURIComponent(bookId)}${updatedAfter ? `?updatedAfter=${encodeURIComponent(updatedAfter)}` : ''}`);
export const pushInk = (body: { bookId: string; pageId: string; baseRev: number; ink: InkPage; checksum: string }) =>
  api<InkPushResponse>('/ink', { method: 'PUT', body: JSON.stringify({ ...body, deviceId: deviceId() }) });

// ---------- 저장소 (사생활 보호 모드 등에서 실패해도 동작) ----------

function safeGet(k: string): string | null {
  try { return localStorage.getItem(k); } catch { return null; }
}
function safeSet(k: string, v: string) {
  try { localStorage.setItem(k, v); } catch { /* 저장 불가 환경 */ }
}
function safeDel(k: string) {
  try { localStorage.removeItem(k); } catch { /* 저장 불가 환경 */ }
}
