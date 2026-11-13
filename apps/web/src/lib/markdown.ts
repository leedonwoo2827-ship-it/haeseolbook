import katex from 'katex';

/**
 * 해설용 최소 Markdown → HTML. 원문을 먼저 이스케이프하므로 HTML 주입이 불가능하다.
 * 지원: ### 제목, **굵게**, - 목록, 빈 줄 문단, $수식$, $$수식$$
 */
const esc = (s: string) => s.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);

function math(tex: string, display: boolean): string {
  try {
    return katex.renderToString(tex, { displayMode: display, throwOnError: false, output: 'html' });
  } catch {
    return `<code>${esc(tex)}</code>`;
  }
}

function inline(text: string): string {
  // 수식을 먼저 자리표시로 빼 둔다 (수식 안의 * 가 굵게로 바뀌지 않도록)
  const slots: string[] = [];
  const keep = (html: string) => `\u0000${slots.push(html) - 1}\u0000`;
  let s = text.replace(/\$\$([^$]+)\$\$/g, (_, t) => keep(math(t, true))).replace(/\$([^$\n]+)\$/g, (_, t) => keep(math(t, false)));
  s = esc(s).replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>').replace(/`([^`]+)`/g, '<code>$1</code>');
  return s.replace(/\u0000(\d+)\u0000/g, (_, i) => slots[Number(i)]);
}

/** 해설 그림 주소표(교재를 열 때 Reader 가 채운다) — ![설명](img:이름) 를 이 주소의 그림으로 */
let IMAGES: Record<string, string> = {};
export function setImageMap(map: Record<string, string> | undefined): void { IMAGES = map ?? {}; }

export function renderMarkdown(md: string): string {
  const out: string[] = [];
  let list: string[] = [];
  let para: string[] = [];
  let table: string[][] = [];
  const cells = (row: string) => row.replace(/^\||\|$/g, '').split('|').map((c) => c.trim());
  const flush = () => {
    if (para.length) out.push(`<p>${inline(para.join(' '))}</p>`);
    if (list.length) out.push(`<ul>${list.map((l) => `<li>${inline(l)}</li>`).join('')}</ul>`);
    if (table.length) {
      const [head, ...body] = table;
      out.push(`<table><thead><tr>${head.map((c) => `<th>${inline(c)}</th>`).join('')}</tr></thead><tbody>${
        body.map((r) => `<tr>${r.map((c) => `<td>${inline(c)}</td>`).join('')}</tr>`).join('')}</tbody></table>`);
    }
    para = [];
    list = [];
    table = [];
  };
  for (const raw of md.split(/\r?\n/)) {
    const line = raw.trim();
    const h = /^(#{1,4})\s+(.*)$/.exec(line);
    if (/^\|.*\|$/.test(line)) {
      if (para.length || list.length) flush();
      if (!/^\|[\s:|-]+\|$/.test(line)) table.push(cells(line));   // 구분선(|---|) 은 건너뜀
      continue;
    }
    if (table.length) flush();
    // ![설명](img:이름) 또는 ![설명](img:이름|보일 폭px) — 2배로 그린 그림은 폭을 절반으로 적어 둔다(글씨가 본문과 같은 크기)
    const img = /^!\[([^\]]*)\]\(img:([A-Za-z0-9_.-]+)(?:\|(\d{2,4}))?\)$/.exec(line);
    if (img) {
      flush();
      const src = IMAGES[img[2]];
      const w = img[3] ? ` style="width:${Number(img[3])}px"` : '';
      out.push(src ? `<figure class="sol-fig"><img src="${esc(src)}" alt="${esc(img[1])}" loading="lazy"${w}><figcaption>${esc(img[1])}</figcaption></figure>`
                   : `<p class="muted">(그림: ${esc(img[1])})</p>`);
      continue;
    }
    if (!line) flush();
    else if (h) { flush(); out.push(`<h4>${inline(h[2])}</h4>`); }
    else if (/^[-*]\s+/.test(line)) { if (para.length) flush(); list.push(line.replace(/^[-*]\s+/, '')); }
    else { if (list.length) flush(); para.push(line); }
  }
  flush();
  return out.join('');
}
