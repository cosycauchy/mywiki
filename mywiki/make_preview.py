#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dist/ 전체를 단일 HTML 파일로 묶어 미리보기용으로 만듭니다."""
import os, re, json, html

DIST = "dist"
css = open(os.path.join(DIST, "style.css"), encoding="utf-8").read()
index = json.load(open(os.path.join(DIST, "search.json"), encoding="utf-8"))

pages = {}
for root, _, files in os.walk(DIST):
    for fn in files:
        if not fn.endswith(".html"):
            continue
        p = os.path.join(root, fn)
        rel = os.path.relpath(p, DIST).replace(os.sep, "/")
        src = open(p, encoding="utf-8").read()
        if "http-equiv=\"refresh\"" in src:
            continue
        m = re.search(r"<main>(.*?)</main>", src, re.S)
        t = re.search(r'<h1 class="title">(.*?)</h1>', src, re.S)
        if not m:
            continue
        body = m.group(1)
        # 상대경로를 페이지 키로 정규화
        base = os.path.dirname(rel)
        def fix(mm):
            href = mm.group(1)
            if href.startswith(("http", "#")):
                return mm.group(0)
            norm = os.path.normpath(os.path.join(base, href)).replace(os.sep, "/")
            return 'href="#%s"' % norm
        body = re.sub(r'href="([^"]+)"', fix, body)
        pages[rel] = {"t": html.unescape(re.sub("<[^>]+>", "", t.group(1))) if t else rel,
                      "h": body}

start = "w/FrontPage.html"
out = """<!DOCTYPE html><html lang="ko"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>주환위키 (미리보기)</title>
<style>%s
.pv{position:fixed;right:12px;bottom:12px;background:var(--accent);color:#fff;
 font-size:12px;padding:6px 11px;border-radius:20px;opacity:.9;z-index:99}
</style></head><body>
<header class="top"><div class="topin">
 <a class="brand" href="#%s">주환위키</a>
 <div class="sbox"><input id="q" type="search" placeholder="검색" autocomplete="off">
 <div class="results" id="res"></div></div>
 <button class="tbtn" id="tbtn" onclick="toggleTheme()">&#9790;</button>
</div></header>
<main id="app"></main>
<footer>주환위키 · 정적 위키 · 서버 없음</footer>
<div class="pv">단일 파일 미리보기</div>
<script>
var PAGES=%s, IDX=%s, START=%s;
function resolve(h){
  if(!h) return START;
  if(PAGES[h]) return h;
  try{ var d=decodeURIComponent(h); if(PAGES[d]) return d; }catch(e){}
  try{ var e2=encodeURIComponent(h); if(PAGES[e2]) return e2; }catch(e){}
  return START;
}
function go(k){
  var p=PAGES[resolve(k)];
  document.getElementById('app').innerHTML=p.h;
  document.title=p.t+' - 주환위키';
  window.scrollTo(0,0);
}
window.addEventListener('hashchange',function(){go(location.hash.slice(1))});
var K='wiki-theme';
var t=localStorage.getItem?(localStorage.getItem(K)||''):'';
if(!t) t=matchMedia('(prefers-color-scheme:dark)').matches?'dark':'light';
document.documentElement.setAttribute('data-theme',t);
function toggleTheme(){
  var c=document.documentElement.getAttribute('data-theme')==='dark'?'light':'dark';
  document.documentElement.setAttribute('data-theme',c);
  try{localStorage.setItem(K,c)}catch(e){}
  document.getElementById('tbtn').innerHTML=c==='dark'?'&#9728;':'&#9790;';
}
document.getElementById('tbtn').innerHTML=t==='dark'?'&#9728;':'&#9790;';
var inp=document.getElementById('q'), box=document.getElementById('res');
function run(){
  var q=inp.value.trim().toLowerCase();
  if(!q){box.style.display='none';return}
  var hits=[];
  for(var i=0;i<IDX.length&&hits.length<12;i++){
    var d=IDX[i], ti=d.t.toLowerCase().indexOf(q), bi=d.b.toLowerCase().indexOf(q);
    if(ti>=0||bi>=0){
      var sn=''; if(bi>=0){var s=Math.max(0,bi-30);sn=(s?'\\u2026':'')+d.b.substr(s,90)+'\\u2026';}
      hits.push({d:d,sn:sn,r:ti>=0?0:1});
    }
  }
  hits.sort(function(a,b){return a.r-b.r});
  box.innerHTML=hits.length?hits.map(function(h){
    return '<a href="#'+h.d.u+'"><b>'+h.d.t+'</b>'+(h.sn?'<span class="snip">'+h.sn+'</span>':'')+'</a>';
  }).join(''):'<a style="color:var(--muted)">\\uACB0\\uACFC \\uC5C6\\uC74C</a>';
  box.style.display='block';
}
inp.addEventListener('input',run); inp.addEventListener('focus',run);
document.addEventListener('click',function(e){
  if(!e.target.closest('.sbox')) box.style.display='none';
});
go(location.hash.slice(1));
</script></body></html>""" % (
    css, start,
    json.dumps(pages, ensure_ascii=False),
    json.dumps(index, ensure_ascii=False),
    json.dumps(start, ensure_ascii=False),
)

with open("preview.html", "w", encoding="utf-8") as f:
    f.write(out)
print("preview.html 생성 (%d개 페이지, %.0fKB)" % (len(pages), len(out) / 1024))
