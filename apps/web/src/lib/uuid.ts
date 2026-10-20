/**
 * UUID v4. crypto.randomUUID 는 보안 컨텍스트(https·localhost)에서만 있어서
 * 사내 랜 주소(http://192.168.x.x)로 열면 없다 → getRandomValues 로 만든다(이건 http 에서도 된다).
 */
export function uuid(): string {
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID();
  const b = crypto.getRandomValues(new Uint8Array(16));
  b[6] = (b[6] & 0x0f) | 0x40;
  b[8] = (b[8] & 0x3f) | 0x80;
  const h = [...b].map((x) => x.toString(16).padStart(2, '0')).join('');
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
}
