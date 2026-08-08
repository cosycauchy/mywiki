#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
나무위키 스타일 정적 위키 빌더
docs/*.namu 파일을 읽어 dist/ 에 HTML을 생성합니다.
외부 라이브러리 없이 파이썬 표준 라이브러리만 사용합니다.
"""

import os, re, json, html, shutil, urllib.parse
from datetime import datetime, timezone, timedelta

# ─────────────────────────────────────────────────────────
# 설정 (config.json 으로 덮어쓸 수 있음)
# ─────────────────────────────────────────────────────────
CONFIG = {
    "site_name": "개인 위키",
    "front_page": "FrontPage",
    "github_repo": "",          # 예: "joohwan/mywiki"  → 편집 버튼 활성화
    "github_branch": "main",
    "docs_dir": "docs",
    "out_dir": "dist",
}
if os.path.exists("config.json"):
    with open("config.json", encoding="utf-8") as f:
        CONFIG.update(json.load(f))

DOCS_DIR = CONFIG["docs_dir"]
OUT_DIR = CONFIG["out_dir"]
KST = timezone(timedelta(hours=9))

ALL_DOCS = set()   # 존재하는 문서 이름
CATEGORIES = {}    # 분류명 -> [문서명]


def esc(s):
    return html.escape(s, quote=False)


def slug(name):
    """문서 이름 -> 디스크에 저장할 파일 이름 (한글 그대로, 공백만 _)"""
    return name.replace(" ", "_").replace("/", "／")


def enc(s):
    """디스크 파일 이름 -> URL에 넣을 퍼센트 인코딩 문자열"""
    return urllib.parse.quote(s, safe="")


def doc_url(name):
    return "w/" + enc(slug(name)) + ".html"


def cat_url(name):
    return "c/" + enc(slug(name)) + ".html"


# ─────────────────────────────────────────────────────────
# 인라인 문법
# ─────────────────────────────────────────────────────────
def inline(text, ctx):
    out = []
    i = 0
    n = len(text)

    def literal(s):
        return "\x00LIT%d\x00" % _stash(s)

    stash = ctx.setdefault("_stash", [])

    def _stash(s):
        stash.append(s)
        return len(stash) - 1

    while i < n:
        # 각주 [* ... ]  (중첩 대괄호 허용)
        if text.startswith("[*", i):
            depth, j = 1, i + 2
            while j < n and depth:
                if text[j] == "[":
                    depth += 1
                elif text[j] == "]":
                    depth -= 1
                j += 1
            body = text[i + 2:j - 1].strip()
            ctx["footnotes"].append(body)
            k = len(ctx["footnotes"])
            out.append(literal(
                '<sup class="fn-ref" id="rfn-%d"><a href="#fn-%d">[%d]</a></sup>' % (k, k, k)))
            i = j
            continue

        # 링크 [[ ... ]]
        if text.startswith("[[", i):
            j = text.find("]]", i)
            if j != -1:
                inner = text[i + 2:j]
                i = j + 2
                if "|" in inner:
                    target, label = inner.split("|", 1)
                else:
                    target, label = inner, inner
                target, label = target.strip(), label.strip()

                if target.startswith("분류:"):
                    cat = target[3:].strip()
                    ctx["categories"].append(cat)
                    continue  # 본문에는 출력하지 않음(상단 분류바로 감)

                if re.match(r"^https?://", target):
                    out.append(literal('<a class="ext" href="%s" target="_blank" rel="noopener">%s</a>'
                                       % (esc(target), esc(label))))
                else:
                    cls = "" if target in ALL_DOCS else " not-exist"
                    out.append(literal('<a class="wl%s" href="{{ROOT}}%s">%s</a>'
                                       % (cls, doc_url(target), esc(label))))
                continue

        # 인라인 코드 {{{ ... }}}
        if text.startswith("{{{", i):
            j = text.find("}}}", i)
            if j != -1:
                body = text[i + 3:j]
                i = j + 3
                m = re.match(r"^#([0-9a-zA-Z#]+)\s(.*)$", body, re.S)
                if m:
                    out.append(literal('<span style="color:%s">%s</span>'
                                       % (esc(m.group(1)), esc(m.group(2)))))
                else:
                    out.append(literal('<code>%s</code>' % esc(body)))
                continue

        out.append(text[i])
        i += 1

    s = "".join(out)
    s = esc(s)

    # 꾸미기 (이스케이프 후 적용 — 마커에 특수문자 없음)
    s = re.sub(r"'''(.+?)'''", r"<b>\1</b>", s, flags=re.S)
    s = re.sub(r"''(.+?)''", r"<i>\1</i>", s, flags=re.S)
    s = re.sub(r"__(.+?)__", r"<u>\1</u>", s, flags=re.S)
    s = re.sub(r"~~(.+?)~~", r"<del>\1</del>", s, flags=re.S)

    # 보관해둔 HTML 복원
    s = re.sub(r"\x00LIT(\d+)\x00", lambda m: stash[int(m.group(1))], s)
    s = s.replace("\x01BR\x01", "<br>")
    return s


# ─────────────────────────────────────────────────────────
# 블록 파서
# ─────────────────────────────────────────────────────────
def parse(src, ctx):
    lines = src.split("\n")
    out = []
    toc = []
    counters = [0, 0, 0, 0, 0]
    i = 0
    has_toc_marker = False

    def close_list(stack):
        while stack:
            out.append("</%s>" % stack.pop())

    list_stack = []

    while i < len(lines):
        line = lines[i]

        # 목차 마커
        if line.strip() == "[목차]":
            close_list(list_stack)
            out.append("\x00TOC\x00")
            has_toc_marker = True
            i += 1
            continue

        # 코드블록 / 접기
        if line.strip().startswith("{{{"):
            first = line.strip()
            buf = []
            fold = re.match(r"^\{\{\{#!folding\s*(.*)$", first)
            ibox = re.match(r"^\{\{\{#!infobox\s*(.*)$", first)
            lang = re.match(r"^\{\{\{#!(?:syntax|code)\s*(\w+)?\s*$", first)
            i += 1
            depth = 1
            while i < len(lines):
                if lines[i].strip().startswith("{{{"):
                    depth += 1
                if lines[i].strip().endswith("}}}"):
                    depth -= 1
                    if depth == 0:
                        break
                buf.append(lines[i])
                i += 1
            i += 1
            close_list(list_stack)
            body = "\n".join(buf)
            if fold:
                title = fold.group(1).strip() or "펼치기 · 접기"
                out.append('<details class="fold"><summary>%s</summary><div class="fold-body">%s</div></details>'
                           % (esc(title), parse(body, ctx)[0]))
            elif ibox:
                title = ibox.group(1).strip()
                rows = []
                for ln in body.split("\n"):
                    ln = ln.strip()
                    if not ln:
                        continue
                    if ln.startswith("||") and ln.endswith("||"):
                        cells = ln.strip("|").split("||")
                        if len(cells) >= 2:
                            rows.append('<tr><th>%s</th><td>%s</td></tr>'
                                        % (inline(cells[0].strip(), ctx),
                                           inline("||".join(cells[1:]).strip(), ctx)))
                        else:
                            rows.append('<tr><td class="ib-full" colspan="2">%s</td></tr>'
                                        % inline(cells[0].strip(), ctx))
                    elif ln.startswith("---"):
                        rows.append('<tr><td class="ib-sep" colspan="2"></td></tr>')
                    else:
                        rows.append('<tr><td class="ib-full" colspan="2">%s</td></tr>'
                                    % inline(ln, ctx))
                head = '<div class="ib-title">%s</div>' % inline(title, ctx) if title else ""
                out.append('<aside class="ibox">%s<table>%s</table></aside>'
                           % (head, "".join(rows)))
            else:
                out.append('<pre class="code"><code>%s</code></pre>' % esc(body))
            continue

        # 문단 제목
        m = re.match(r"^(={2,6})\s*(.+?)\s*\1\s*$", line)
        if m:
            close_list(list_stack)
            lv = len(m.group(1)) - 1          # == → 1단계
            counters[lv - 1] += 1
            for k in range(lv, 5):
                counters[k] = 0
            num = ".".join(str(c) for c in counters[:lv] if True)
            num = ".".join(str(counters[k]) for k in range(lv))
            title = m.group(2)
            anchor = "s-" + num
            toc.append((lv, num, title, anchor))
            out.append('<h%d id="%s" class="head"><a class="hnum" href="#%s">%s.</a> %s</h%d>'
                       % (min(lv + 1, 6), anchor, anchor, num, inline(title, ctx), min(lv + 1, 6)))
            i += 1
            continue

        # 수평선
        if re.match(r"^-{4,}\s*$", line):
            close_list(list_stack)
            out.append("<hr>")
            i += 1
            continue

        # 표
        if line.strip().startswith("||") and line.strip().endswith("||"):
            close_list(list_stack)
            rows = []
            while i < len(lines) and lines[i].strip().startswith("||"):
                cells = [c for c in lines[i].strip().strip("|").split("||")]
                rows.append(cells)
                i += 1
            out.append('<div class="tw"><table>')
            for r_i, row in enumerate(rows):
                out.append("<tr>")
                for c in row:
                    c = c.strip()
                    is_head = c.startswith("'''") and c.endswith("'''")
                    tag = "th" if is_head else "td"
                    out.append("<%s>%s</%s>" % (tag, inline(c, ctx), tag))
                out.append("</tr>")
            out.append("</table></div>")
            continue

        # 인용문
        if line.startswith(">"):
            close_list(list_stack)
            buf = []
            while i < len(lines) and lines[i].startswith(">"):
                buf.append(lines[i].lstrip(">").strip())
                i += 1
            out.append("<blockquote>%s</blockquote>" % inline("\x01BR\x01".join(buf), ctx))
            continue

        # 목록 (앞 공백 + * 또는 1.)
        m = re.match(r"^(\s+)([*]|\d+\.)\s+(.*)$", line)
        if m:
            depth = (len(m.group(1)) + 1) // 1
            depth = len(m.group(1))
            tag = "ul" if m.group(2) == "*" else "ol"
            while len(list_stack) > depth:
                out.append("</%s>" % list_stack.pop())
            while len(list_stack) < depth:
                out.append("<%s>" % tag)
                list_stack.append(tag)
            out.append("<li>%s</li>" % inline(m.group(3), ctx))
            i += 1
            continue

        # 빈 줄
        if not line.strip():
            close_list(list_stack)
            i += 1
            continue

        # 일반 문단
        close_list(list_stack)
        buf = []
        while i < len(lines) and lines[i].strip() and not re.match(
                r"^(\s+[*]|\s+\d+\.|={2,6}|\|\||>|-{4,}|\{\{\{|\[목차\])", lines[i]):
            buf.append(lines[i])
            i += 1
        if buf:
            out.append("<p>%s</p>" % inline("\x01BR\x01".join(buf), ctx))

    close_list(list_stack)
    return "\n".join(out), toc, has_toc_marker


# ─────────────────────────────────────────────────────────
# 템플릿
# ─────────────────────────────────────────────────────────
CSS = """
:root{
  --bg:#fff; --fg:#212529; --muted:#6c757d; --line:#e5e5e5;
  --accent:#00a495; --link:#0275d8; --red:#ff0000;
  --box:#f8f9fa; --head-bg:#f1f3f5; --top:#fff; --shadow:0 1px 3px rgba(0,0,0,.08);
}
html[data-theme=dark]{
  --bg:#1c1d1f; --fg:#dcdcdc; --muted:#9aa0a6; --line:#37383a;
  --accent:#3bbdb1; --link:#5fa8ea; --red:#ff6b6b;
  --box:#26272a; --head-bg:#232427; --top:#232427; --shadow:0 1px 3px rgba(0,0,0,.4);
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
  font-family:-apple-system,BlinkMacSystemFont,"Pretendard","Apple SD Gothic Neo","Malgun Gothic",sans-serif;
  font-size:16px;line-height:1.7;-webkit-text-size-adjust:100%}
a{color:var(--link);text-decoration:none}
a:hover{text-decoration:underline}
a.not-exist{color:var(--red)}
a.ext::after{content:"↗";font-size:.75em;vertical-align:super;opacity:.6}

header.top{position:sticky;top:0;z-index:50;background:var(--top);
  border-bottom:1px solid var(--line);box-shadow:var(--shadow)}
.topin{max-width:1000px;margin:0 auto;display:flex;align-items:center;gap:12px;
  padding:10px 16px}
.brand{font-weight:700;color:var(--accent);font-size:17px;white-space:nowrap}
.brand:hover{text-decoration:none}
.sbox{flex:1;position:relative}
.sbox input{width:100%;padding:7px 12px;border:1px solid var(--line);border-radius:6px;
  background:var(--bg);color:var(--fg);font-size:14px;outline:none}
.sbox input:focus{border-color:var(--accent)}
.results{position:absolute;left:0;right:0;top:110%;background:var(--bg);
  border:1px solid var(--line);border-radius:6px;box-shadow:var(--shadow);
  max-height:60vh;overflow:auto;display:none}
.results a{display:block;padding:9px 12px;border-bottom:1px solid var(--line);color:var(--fg)}
.results a:hover{background:var(--box);text-decoration:none}
.results .snip{font-size:12px;color:var(--muted);display:block}
.tbtn{border:1px solid var(--line);background:var(--bg);color:var(--fg);
  border-radius:6px;padding:6px 10px;cursor:pointer;font-size:14px}

main{max-width:1000px;margin:0 auto;padding:20px 16px 80px}
.title{font-size:30px;font-weight:700;margin:8px 0 4px}
.meta{color:var(--muted);font-size:13px;margin-bottom:12px}
.actions{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:20px}
.actions a{border:1px solid var(--line);border-radius:6px;padding:5px 12px;
  font-size:13px;color:var(--fg);background:var(--box)}
.actions a:hover{text-decoration:none;border-color:var(--accent);color:var(--accent)}

.catbar{border:1px solid var(--line);border-radius:6px;padding:8px 12px;
  font-size:13.5px;margin-bottom:18px;background:var(--box)}

.toc{display:inline-block;min-width:min(100%,260px);max-width:100%;
  border:1px solid var(--line);border-radius:6px;background:var(--box);
  padding:12px 18px 12px 12px;margin:0 0 22px}
.toc .toch{font-weight:700;margin-bottom:6px}
.toc ul{list-style:none;margin:0;padding-left:14px}
.toc>ul{padding-left:0}
.toc li{font-size:14px;line-height:1.65}

h2.head,h3.head,h4.head,h5.head,h6.head{
  border-bottom:1px solid var(--line);padding-bottom:6px;margin:34px 0 14px;font-weight:700}
h2.head{font-size:23px} h3.head{font-size:20px} h4.head{font-size:18px}
h5.head,h6.head{font-size:16px}
.hnum{color:var(--accent)}
.hnum:hover{text-decoration:none}

p{margin:12px 0}
ul,ol{margin:10px 0;padding-left:26px}
li{margin:3px 0}
blockquote{margin:14px 0;padding:10px 16px;border-left:4px solid var(--accent);
  background:var(--box);border-radius:0 6px 6px 0}
blockquote p{margin:0}
hr{border:0;border-top:1px solid var(--line);margin:26px 0}

.tw{overflow-x:auto;margin:16px 0}
table{border-collapse:collapse;font-size:14.5px}
th,td{border:1px solid var(--line);padding:7px 12px;text-align:left}
th{background:var(--head-bg);font-weight:700}

pre.code{background:var(--box);border:1px solid var(--line);border-radius:6px;
  padding:14px 16px;overflow-x:auto;font-size:13.5px;line-height:1.55}
code{background:var(--box);border:1px solid var(--line);border-radius:4px;
  padding:1px 5px;font-size:.9em}
pre.code code{background:none;border:0;padding:0}

/* 인물 문서 인포박스 */
.ibox{float:right;width:320px;max-width:100%;margin:0 0 18px 24px;
  border:1px solid var(--line);border-radius:8px;overflow:hidden;
  background:var(--box);box-shadow:var(--shadow)}
.ib-title{background:var(--accent);color:#fff;font-weight:700;
  padding:10px 14px;font-size:15.5px;text-align:center}
.ibox table{width:100%;border-collapse:collapse;font-size:13.5px}
.ibox th{width:34%;background:var(--head-bg);border:0;border-bottom:1px solid var(--line);
  padding:8px 10px;text-align:center;vertical-align:middle;font-weight:600;white-space:nowrap}
.ibox td{border:0;border-bottom:1px solid var(--line);padding:8px 12px;
  vertical-align:middle;line-height:1.55}
.ibox tr:last-child th,.ibox tr:last-child td{border-bottom:0}
.ibox td.ib-full{text-align:center;background:var(--head-bg);font-weight:600}
.ibox td.ib-sep{padding:0;height:4px;background:var(--line)}
@media(max-width:720px){.ibox{float:none;width:100%;margin:0 0 18px}}

details.fold{border:1px solid var(--line);border-radius:6px;margin:14px 0;background:var(--box)}
details.fold summary{cursor:pointer;padding:9px 14px;font-weight:600;font-size:14.5px}
.fold-body{padding:2px 14px 12px}

.fn-ref a{font-size:.8em}
.footnotes{margin-top:44px;border-top:1px solid var(--line);padding-top:14px;font-size:14px}
.footnotes ol{padding-left:22px}
.footnotes li{margin:5px 0}

footer{max-width:1000px;margin:0 auto;padding:22px 16px 60px;
  color:var(--muted);font-size:13px;border-top:1px solid var(--line)}
.doclist{columns:2;column-gap:28px}
@media(max-width:640px){
  .doclist{columns:1}
  .title{font-size:25px}
  body{font-size:15.5px}
  .brand{font-size:15px}
}
"""

JS = """
(function(){
  var K='wiki-theme';
  var t=localStorage.getItem(K)||(matchMedia('(prefers-color-scheme:dark)').matches?'dark':'light');
  document.documentElement.setAttribute('data-theme',t);
  window.toggleTheme=function(){
    var c=document.documentElement.getAttribute('data-theme')==='dark'?'light':'dark';
    document.documentElement.setAttribute('data-theme',c);
    localStorage.setItem(K,c);
    var b=document.getElementById('tbtn'); if(b) b.textContent = c==='dark'?'\\u2600':'\\u263D';
  };
  document.addEventListener('DOMContentLoaded',function(){
    var b=document.getElementById('tbtn');
    if(b) b.textContent=document.documentElement.getAttribute('data-theme')==='dark'?'\\u2600':'\\u263D';

    var inp=document.getElementById('q'), box=document.getElementById('res'), idx=null;
    if(!inp) return;
    function load(cb){
      if(idx) return cb();
      fetch(ROOT+'search.json').then(function(r){return r.json()}).then(function(d){idx=d;cb()});
    }
    function run(){
      var q=inp.value.trim().toLowerCase();
      if(!q){box.style.display='none';return}
      load(function(){
        var hits=[];
        for(var i=0;i<idx.length&&hits.length<12;i++){
          var d=idx[i];
          var ti=d.t.toLowerCase().indexOf(q), bi=d.b.toLowerCase().indexOf(q);
          if(ti>=0||bi>=0){
            var sn='';
            if(bi>=0){var s=Math.max(0,bi-30);sn=(s?'\\u2026':'')+d.b.substr(s,90)+'\\u2026';}
            hits.push({d:d,sn:sn,rank:ti>=0?0:1});
          }
        }
        hits.sort(function(a,b){return a.rank-b.rank});
        box.innerHTML=hits.length?hits.map(function(h){
          return '<a href="'+ROOT+h.d.u+'"><b>'+h.d.t+'</b>'+(h.sn?'<span class="snip">'+h.sn+'</span>':'')+'</a>';
        }).join(''):'<a style="color:var(--muted)">\\uACB0\\uACFC \\uC5C6\\uC74C</a>';
        box.style.display='block';
      });
    }
    inp.addEventListener('input',run);
    inp.addEventListener('focus',run);
    document.addEventListener('click',function(e){
      if(!e.target.closest('.sbox')) box.style.display='none';
    });
  });
})();
"""


def page(title, body, root, extra_meta="", actions="", catbar=""):
    repo = CONFIG.get("github_repo", "")
    return f"""<!DOCTYPE html>
<html lang="ko"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>{esc(title)} - {esc(CONFIG['site_name'])}</title>
<link rel="stylesheet" href="{root}style.css">
<script>var ROOT="{root}";</script>
<script src="{root}app.js"></script>
</head><body>
<header class="top"><div class="topin">
  <a class="brand" href="{root}index.html">{esc(CONFIG['site_name'])}</a>
  <div class="sbox">
    <input id="q" type="search" placeholder="검색" autocomplete="off">
    <div class="results" id="res"></div>
  </div>
  <button class="tbtn" id="tbtn" onclick="toggleTheme()">☾</button>
</div></header>
<main>
  <h1 class="title">{esc(title)}</h1>
  <div class="meta">{extra_meta}</div>
  <div class="actions">{actions}</div>
  {catbar}
  {body}
</main>
<footer>{esc(CONFIG['site_name'])} · 정적 위키 · 서버 없음</footer>
</body></html>"""


# ─────────────────────────────────────────────────────────
# 빌드
# ─────────────────────────────────────────────────────────
def build():
    global ALL_DOCS, CATEGORIES
    CATEGORIES = {}

    files = sorted(f for f in os.listdir(DOCS_DIR) if f.endswith(".namu"))
    names = [os.path.splitext(f)[0].replace("_", " ") for f in files]
    ALL_DOCS = set(names)

    if os.path.exists(OUT_DIR):
        shutil.rmtree(OUT_DIR)
    os.makedirs(os.path.join(OUT_DIR, "w"), exist_ok=True)

    with open(os.path.join(OUT_DIR, "style.css"), "w", encoding="utf-8") as f:
        f.write(CSS)
    with open(os.path.join(OUT_DIR, "app.js"), "w", encoding="utf-8") as f:
        f.write(JS)

    index = []
    repo = CONFIG.get("github_repo", "")
    branch = CONFIG.get("github_branch", "main")

    for fn, name in zip(files, names):
        path = os.path.join(DOCS_DIR, fn)
        with open(path, encoding="utf-8") as f:
            src = f.read()

        ctx = {"footnotes": [], "categories": []}
        body, toc, has_toc = parse(src, ctx)

        # 목차 HTML
        if toc:
            items, prev = [], 0
            for lv, num, title, anchor in toc:
                while prev < lv:
                    items.append("<ul>")
                    prev += 1
                while prev > lv:
                    items.append("</ul>")
                    prev -= 1
                items.append('<li><a href="#%s">%s. %s</a></li>'
                             % (anchor, num, esc(re.sub(r"'''|''|__|~~", "", title))))
            while prev > 0:
                items.append("</ul>")
                prev -= 1
            toc_html = '<div class="toc"><div class="toch">목차</div>%s</div>' % "".join(items)
        else:
            toc_html = ""
        body = body.replace("\x00TOC\x00", toc_html)

        # 각주
        if ctx["footnotes"]:
            fns = "".join('<li id="fn-%d">%s <a href="#rfn-%d">↩</a></li>'
                          % (k + 1, inline(t, {"footnotes": [], "categories": []}), k + 1)
                          for k, t in enumerate(ctx["footnotes"]))
            body += '<div class="footnotes"><ol>%s</ol></div>' % fns

        # 분류
        catbar = ""
        if ctx["categories"]:
            links = " · ".join('<a href="{{ROOT}}%s">%s</a>' % (cat_url(c), esc(c))
                               for c in ctx["categories"])
            catbar = '<div class="catbar">분류: %s</div>' % links
            for c in ctx["categories"]:
                CATEGORIES.setdefault(c, []).append(name)

        mtime = datetime.fromtimestamp(os.path.getmtime(path), KST).strftime("%Y-%m-%d %H:%M")
        actions = ('<a href="{{ROOT}}index.html">문서 목록</a>'
                   '<a href="{{ROOT}}c/index.html">분류</a>')
        if repo:
            edit = "https://github.com/%s/edit/%s/%s/%s" % (repo, branch, DOCS_DIR, fn)
            hist = "https://github.com/%s/commits/%s/%s/%s" % (repo, branch, DOCS_DIR, fn)
            actions = ('<a href="%s" target="_blank">✏ 편집</a>'
                       '<a href="%s" target="_blank">역사</a>' % (edit, hist)) + actions

        htmlpage = page(name, body, "../", "최근 수정 : " + mtime, actions, catbar)
        htmlpage = htmlpage.replace("{{ROOT}}", "../")
        with open(os.path.join(OUT_DIR, "w", slug(name) + ".html"), "w", encoding="utf-8") as f:
            f.write(htmlpage)

        plain = re.sub(r"<[^>]+>", "", body)
        plain = re.sub(r"\s+", " ", html.unescape(plain)).strip()
        index.append({"t": name, "u": doc_url(name), "b": plain[:900]})

    # 분류 페이지
    os.makedirs(os.path.join(OUT_DIR, "c"), exist_ok=True)
    for cat, members in CATEGORIES.items():
        lis = "".join('<li><a href="../%s">%s</a></li>' % (doc_url(m), esc(m))
                      for m in sorted(members))
        b = '<ul class="doclist">%s</ul>' % lis
        p = page("분류: " + cat, b, "../", "%d개 문서" % len(members),
                 '<a href="../index.html">문서 목록</a><a href="index.html">분류 목록</a>')
        with open(os.path.join(OUT_DIR, "c", slug(cat) + ".html"), "w", encoding="utf-8") as f:
            f.write(p.replace("{{ROOT}}", "../"))

    lis = "".join('<li><a href="%s.html">%s</a> <span style="color:var(--muted)">(%d)</span></li>'
                  % (enc(slug(c)), esc(c), len(m)) for c, m in sorted(CATEGORIES.items()))
    p = page("분류 목록", '<ul class="doclist">%s</ul>' % (lis or "<li>없음</li>"), "../",
             "%d개 분류" % len(CATEGORIES), '<a href="../index.html">문서 목록</a>')
    with open(os.path.join(OUT_DIR, "c", "index.html"), "w", encoding="utf-8") as f:
        f.write(p.replace("{{ROOT}}", "../"))

    # 문서 목록
    lis = "".join('<li><a href="%s">%s</a></li>' % (doc_url(n), esc(n)) for n in sorted(names))
    p = page("문서 목록", '<ul class="doclist">%s</ul>' % lis, "",
             "%d개 문서" % len(names), '<a href="c/index.html">분류 목록</a>')
    with open(os.path.join(OUT_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(p.replace("{{ROOT}}", ""))

    # 대문 리다이렉트
    fp = CONFIG["front_page"]
    if fp in ALL_DOCS:
        with open(os.path.join(OUT_DIR, "index.html"), "w", encoding="utf-8") as f:
            f.write('<!DOCTYPE html><meta charset="utf-8">'
                    '<meta http-equiv="refresh" content="0;url=%s">' % doc_url(fp))
        p = page("문서 목록", '<ul class="doclist">%s</ul>' % lis, "",
                 "%d개 문서" % len(names), '<a href="c/index.html">분류 목록</a>')
        with open(os.path.join(OUT_DIR, "all.html"), "w", encoding="utf-8") as f:
            f.write(p.replace("{{ROOT}}", ""))

    with open(os.path.join(OUT_DIR, "search.json"), "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False)

    open(os.path.join(OUT_DIR, ".nojekyll"), "w").close()
    print("빌드 완료: %d개 문서, %d개 분류 → %s/" % (len(names), len(CATEGORIES), OUT_DIR))


if __name__ == "__main__":
    build()
