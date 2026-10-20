<?php
declare(strict_types=1);

/**
 * 출판사 사이트 관리자: IP 허브에서 선별한 아이템 패키지 업로드 · 게시/비공개.
 * config 'admin_token'(32자 이상)을 X-Admin-Token 헤더로 보낸다. 비어 있으면 관리자 기능 비활성.
 */

namespace Hsb;

final class Admin
{
    public static function require(Request $req): void
    {
        $token = (string) Config::get('admin_token', '');
        if (strlen($token) < 32) throw new HttpError(403, '관리자 기능이 비활성화되어 있습니다 (config admin_token)');
        if (!hash_equals($token, (string) $req->header('x-admin-token'))) throw new HttpError(401, '관리자 토큰이 올바르지 않습니다');
    }

    public static function books(): array
    {
        return array_map(fn ($b) => [
            'id' => $b['id'], 'title' => $b['title'], 'exam' => $b['exam'], 'subject' => $b['subject'], 'year' => (int) $b['year'],
            'version' => $b['item_version'], 'published' => $b['published_at'] !== null,
            'pages' => (int) $b['pages'], 'quizzes' => (int) $b['quizzes'], 'videos' => (int) $b['videos'], 'readers' => (int) $b['readers'],
        ], Db::all(
            'SELECT b.*, (SELECT COUNT(*) FROM hsb_pages p WHERE p.book_id = b.id) AS pages,
                    (SELECT COUNT(*) FROM hsb_quizzes q WHERE q.book_id = b.id) AS quizzes,
                    (SELECT COUNT(*) FROM hsb_quizzes q WHERE q.book_id = b.id AND q.youtube_id IS NOT NULL) AS videos,
                    (SELECT COUNT(*) FROM hsb_library l WHERE l.book_id = b.id) AS readers
             FROM hsb_books b ORDER BY b.created_at DESC'
        ));
    }

    public static function setPublished(string $id, bool $published): void
    {
        $n = Db::exec('UPDATE hsb_books SET published_at = ? WHERE id = ?', [$published ? now() : null, $id]);
        if ($n === 0) throw new HttpError(404, '교재를 찾을 수 없습니다');
    }

    public static function html(): string
    {
        return <<<'HTML'
<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex"><title>해설북 관리자</title><style>
:root{--bg:#f6f7f9;--card:#fff;--line:#e5e7eb;--ink:#111827;--sub:#6b7280;--accent:#2563eb;--bad:#dc2626;--ok:#16a34a}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.6 system-ui,-apple-system,'Apple SD Gothic Neo','Malgun Gothic',sans-serif}
main{max-width:920px;margin:0 auto;padding:24px 16px}h1{font-size:22px;margin:0 0 4px}p.sub{color:var(--sub);margin:0 0 20px}
section{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px;margin-bottom:16px}
h2{font-size:16px;margin:0 0 12px}input[type=password],input[type=file]{width:100%;padding:10px;border:1px solid var(--line);border-radius:8px;background:#fff}
button{padding:9px 14px;border-radius:8px;border:1px solid var(--line);background:#fff;cursor:pointer;font:inherit}
button.primary{background:var(--ink);color:#fff;border-color:var(--ink)}.row{display:flex;gap:8px;align-items:center;margin-top:10px;flex-wrap:wrap}
table{width:100%;border-collapse:collapse;font-size:14px}th,td{text-align:left;padding:8px 6px;border-bottom:1px solid var(--line)}th{color:var(--sub);font-weight:600}
.tag{display:inline-block;padding:1px 8px;border-radius:99px;font-size:12px}.on{background:#dcfce7;color:var(--ok)}.off{background:#f3f4f6;color:var(--sub)}
#msg{min-height:1.6em}.err{color:var(--bad)}.okm{color:var(--ok)}.scroll{overflow-x:auto}
</style></head><body><main>
<h1>해설북 관리자</h1><p class="sub">IP 허브에서 고른 아이템 패키지(.hsbpkg.zip)를 올리고 게시 여부를 관리합니다.</p>
<section><h2>관리자 토큰</h2><input id="tok" type="password" placeholder="config.php 의 admin_token" autocomplete="off">
<div class="row"><button id="save">확인</button></div></section>
<section><h2>패키지 업로드</h2><input id="file" type="file" accept=".zip">
<div class="row"><button id="up" class="primary">업로드 후 게시</button><span id="msg"></span></div></section>
<section><h2>교재</h2><div class="scroll"><table><thead><tr><th>교재</th><th>버전</th><th>문항/영상</th><th>열람자</th><th>상태</th><th></th></tr></thead><tbody id="list"></tbody></table></div></section>
</main><script>
const base = location.pathname.replace(/\/admin\/?$/, '');
const $ = (id) => document.getElementById(id);
const tok = () => sessionStorage.getItem('hsb_admin') || '';
const msg = (t, cls) => { $('msg').textContent = t; $('msg').className = cls || ''; };
async function api(path, opt = {}) {
  const r = await fetch(base + path, { ...opt, headers: { 'X-Admin-Token': tok(), ...(opt.headers || {}) } });
  const b = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(b.message || r.status);
  return b;
}
function esc(s) { return String(s ?? '').replace(/[&<>"']/g, (c) => '&#' + c.charCodeAt(0) + ';'); }
async function load() {
  try {
    const books = await api('/admin/books');
    $('list').innerHTML = books.map((b) => `<tr><td><b>${esc(b.title)}</b><br><small>${esc(b.id)} · ${esc(b.exam)} ${esc(b.subject)} ${b.year}</small></td>
      <td>${esc(b.version || '-')}</td><td>${b.quizzes} / ${b.videos}</td><td>${b.readers}</td>
      <td><span class="tag ${b.published ? 'on' : 'off'}">${b.published ? '게시 중' : '비공개'}</span></td>
      <td><button data-id="${esc(b.id)}" data-p="${b.published ? 0 : 1}">${b.published ? '비공개로' : '게시'}</button></td></tr>`).join('')
      || '<tr><td colspan="6">아직 교재가 없습니다</td></tr>';
  } catch (e) { $('list').innerHTML = `<tr><td colspan="6" class="err">${esc(e.message)}</td></tr>`; }
}
$('save').onclick = () => { sessionStorage.setItem('hsb_admin', $('tok').value.trim()); load(); };
$('up').onclick = async () => {
  const f = $('file').files[0];
  if (!f) return msg('파일을 고르세요', 'err');
  const fd = new FormData(); fd.append('package', f);
  msg('업로드 중…');
  try { const r = await api('/admin/import', { method: 'POST', body: fd }); msg(`게시됨: ${r.id} v${r.version} (문항 ${r.quizzes}, 영상 ${r.videos})`, 'okm'); load(); }
  catch (e) { msg(e.message, 'err'); }
};
$('list').onclick = async (e) => {
  const b = e.target.closest('button[data-id]'); if (!b) return;
  try { await api(`/admin/books/${encodeURIComponent(b.dataset.id)}/publish`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ published: b.dataset.p === '1' }) }); load(); }
  catch (err) { alert(err.message); }
};
if (tok()) load();
</script></body></html>
HTML;
    }
}
