"""preview.html - a page for a person to check the output against the video.

The video plays on the left; on the right is every screenshot with the lines
paired to it. Clicking a timestamp jumps the video there, and the block being
spoken is highlighted while the video plays.
"""
import html
import pathlib

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>__TITLE__ - preview</title>
<style>
:root { --bg:#f4f5f7; --card:#fff; --ink:#1c2330; --dim:#667085; --line:#d9dde5; --hot:#fff4cc; --acc:#1f6feb; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#12151b; --card:#1b2029; --ink:#e6e9ef; --dim:#98a2b3; --line:#2c3340; --hot:#3b3210; --acc:#6ea8ff; }
}
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--ink); font:15px/1.5 Segoe UI, system-ui, sans-serif; }
.wrap { display:grid; grid-template-columns:minmax(320px,46%) 1fr; gap:20px; padding:16px; max-width:1700px; margin:0 auto; }
.left { position:sticky; top:16px; align-self:start; }
video { width:100%; background:#000; border-radius:8px; }
h1 { font-size:18px; margin:0 0 4px; overflow-wrap:anywhere; }
.meta { color:var(--dim); font-size:13px; margin-bottom:10px; }
.now { margin-top:10px; padding:10px 12px; background:var(--card); border:1px solid var(--line); border-radius:8px; min-height:64px; }
.now b { color:var(--acc); font-variant-numeric:tabular-nums; }
.help { color:var(--dim); font-size:13px; margin-top:10px; }
.warn { display:none; margin-top:10px; padding:10px 12px; border:1px solid #d9822b; border-radius:8px; font-size:13px; }
.block { background:var(--card); border:1px solid var(--line); border-radius:8px; padding:12px; margin-bottom:12px; }
.block.on { border-color:var(--acc); box-shadow:0 0 0 2px var(--acc); }
.block img { width:100%; max-width:560px; display:block; border-radius:6px; border:1px solid var(--line); cursor:pointer; }
.cap { color:var(--dim); font-size:13px; margin:0 0 8px; }
button.t { font:inherit; font-variant-numeric:tabular-nums; color:var(--acc); background:none; border:0; padding:0 6px 0 0; cursor:pointer; font-weight:600; }
.line { padding:3px 6px; border-radius:4px; }
.line.on { background:var(--hot); }
.none { color:var(--dim); font-style:italic; }
label { font-size:13px; color:var(--dim); }
@media (max-width: 900px) { .wrap { grid-template-columns:1fr; } .left { position:static; } }
</style></head><body>
<div class="wrap">
 <div class="left">
  <h1>__TITLE__</h1>
  <div class="meta">__META__</div>
  <video id="v" controls preload="metadata" src="__VIDEO__"></video>
  <div class="warn" id="warn">The video could not be loaded from <code>__VIDEO_PATH__</code>.
   If it was moved, the screenshots and transcript on the right are still complete.</div>
  <div class="now" id="now">Press play, or click any timestamp or screenshot.</div>
  <div class="help">The highlighted block is the screenshot and words this tool paired with
   the moment now playing. If they match what you see and hear, the pairing is right.
   <br><label><input type="checkbox" id="follow" checked> Scroll along with the video</label></div>
 </div>
 <div class="right" id="list">
__BLOCKS__
 </div>
</div>
<script>
var v = document.getElementById('v');
var blocks = [].slice.call(document.querySelectorAll('.block'));
var lines = [].slice.call(document.querySelectorAll('.line[data-t]'));
function fmt(t){ t=Math.floor(t); var h=Math.floor(t/3600), m=Math.floor(t%3600/60), s=t%60;
  return (h<10?'0':'')+h+':'+(m<10?'0':'')+m+':'+(s<10?'0':'')+s; }
function seek(t){ v.currentTime = t; v.play(); }
document.getElementById('list').addEventListener('click', function(e){
  var el = e.target.closest('[data-seek]'); if (el) seek(parseFloat(el.getAttribute('data-seek'))); });
function last(items, t){ var hit=null; for (var i=0;i<items.length;i++){ if (parseFloat(items[i].getAttribute('data-t')) <= t+0.05) hit=items[i]; else break; } return hit; }
var curB=null, curL=null;
v.addEventListener('timeupdate', function(){
  var t=v.currentTime, b=last(blocks,t), l=last(lines,t);
  if (l && t > parseFloat(l.getAttribute('data-e')) + 1.5) l=null;
  if (b!==curB){ if(curB) curB.classList.remove('on'); if(b){ b.classList.add('on');
    if (document.getElementById('follow').checked) b.scrollIntoView({behavior:'smooth', block:'center'}); } curB=b; }
  if (l!==curL){ if(curL) curL.classList.remove('on'); if(l) l.classList.add('on'); curL=l; }
  document.getElementById('now').innerHTML = '<b>'+fmt(t)+'</b> ' + (l ? l.querySelector('span').innerHTML : '<span class="none">(no speech)</span>');
});
v.addEventListener('error', function(){ document.getElementById('warn').style.display='block'; });
</script>
</body></html>
"""


def _hms(t):
    t = int(max(0, t))
    return "%02d:%02d:%02d" % (t // 3600, t % 3600 // 60, t % 60)


def block_start(block):
    """When this block begins to apply: its first line, or its screenshot if earlier."""
    if block["lines"]:
        return min(block["time"], block["lines"][0]["start"])
    return block["time"]


def build(video_path, name, meta, blocks):
    out = []
    for b in blocks:
        t0 = block_start(b)
        out.append('<div class="block" data-t="%.2f">' % t0)
        out.append('<p class="cap"><button class="t" data-seek="%.2f">%s</button>screenshot taken at %s</p>'
                   % (b["time"], _hms(b["time"]), _hms(b["time"])))
        if b["file"]:
            out.append('<img loading="lazy" src="frames/%s" alt="%s" data-seek="%.2f">'
                       % (html.escape(b["file"]), _hms(b["time"]), b["time"]))
        if b["lines"]:
            for s in b["lines"]:
                out.append('<div class="line" data-t="%.2f" data-e="%.2f">'
                           '<button class="t" data-seek="%.2f">%s</button><span>%s</span></div>'
                           % (s["start"], s["end"], s["start"], _hms(s["start"]), html.escape(s["text"])))
        else:
            out.append('<div class="none">(no speech)</div>')
        out.append("</div>")
    try:
        uri = pathlib.Path(video_path).as_uri()
    except ValueError:
        uri = ""
    return (PAGE.replace("__BLOCKS__", "\n".join(out))
            .replace("__TITLE__", html.escape(name))
            .replace("__META__", html.escape(meta))
            .replace("__VIDEO_PATH__", html.escape(video_path))
            .replace("__VIDEO__", html.escape(uri, quote=True)))
