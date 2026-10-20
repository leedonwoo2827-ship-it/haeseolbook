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
    if (!line) flush();
    else if (h) { flush(); out.push(`<h4>${inline(h[2])}</h4>`); }
    else if (/^[-*]\s+/.test(line)) { if (para.length) flush(); list.push(line.replace(/^[-*]\s+/, '')); }
    else { if (list.length) flush(); para.push(line); }
  }
  flush();
  return out.join('');
}
