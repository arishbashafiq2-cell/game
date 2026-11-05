"""
Neon Pop AI - a Bubble Shooter for Streamlit with a Groq-powered coach.

The game runs entirely in the browser (HTML5 Canvas + vanilla JS) so Streamlit
reruns never interrupt play. The Groq coach lives in the sidebar and degrades
gracefully (offline tips) when there is no API key or no network.
"""

import random

import streamlit as st
import streamlit.components.v1 as components
from groq import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    Groq,
    RateLimitError,
)

MODEL = "llama-3.1-8b-instant"

st.set_page_config(page_title="Neon Pop AI", page_icon="🫧", layout="wide")

# ---------------------------------------------------------------------------
# Page styling (dark glass look that matches the game)
# ---------------------------------------------------------------------------
st.markdown(
    """
    <style>
      .stApp { background: radial-gradient(1200px 700px at 70% -10%, #2a1458 0%, #0a0d22 60%); }
      [data-testid="stSidebar"] { background: rgba(14,18,44,.85); backdrop-filter: blur(14px);
                                  border-right: 1px solid rgba(120,140,255,.18); }
      h1, h2, h3, p, label, span, div { color: #e8ecff; }
      .block-container { padding-top: 1.4rem; max-width: 760px; }
      .glass { background: rgba(255,255,255,.06); border: 1px solid rgba(255,255,255,.14);
               border-radius: 14px; padding: .8rem 1rem; margin-top: .6rem; line-height: 1.45; }
      iframe { border-radius: 18px; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Groq helpers
# ---------------------------------------------------------------------------
OFFLINE_TIPS = [
    "Aim for clusters near the ceiling: dropping a floating group scores far more than a plain pop.",
    "Use bank shots off the walls to reach buried colors without disturbing the front line.",
    "Swap your bubble (tap the preview or press Space) when the current color has no match.",
    "Keep chain pops going: every consecutive pop raises your combo multiplier.",
    "Watch the row counter - clear space before the next row descends.",
]


def get_secret_key() -> str:
    """Read GROQ_API_KEY from st.secrets; return '' if it is not configured."""
    try:
        return str(st.secrets["GROQ_API_KEY"]).strip()
    except Exception:
        return ""


def ask_groq(api_key: str, system: str, user: str):
    """Call Groq and return (text, error). Never raises."""
    if not api_key:
        return None, "No API key set. Add one in the sidebar to enable the AI features."
    try:
        client = Groq(api_key=api_key, timeout=15.0, max_retries=1)
        res = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.9,
            max_tokens=220,
        )
        return res.choices[0].message.content.strip(), None
    except AuthenticationError:
        return None, "Groq rejected the API key. Check it and try again."
    except RateLimitError:
        return None, "Groq rate limit reached. Wait a moment and try again."
    except APITimeoutError:
        return None, "Groq took too long to respond. The game still works - try again later."
    except APIConnectionError:
        return None, "Could not reach Groq (network issue). The game still works offline."
    except Exception as exc:  # noqa: BLE001 - keep the app alive whatever happens
        return None, f"Groq error: {exc}"


# ---------------------------------------------------------------------------
# Sidebar: key + AI coach + challenge generator
# ---------------------------------------------------------------------------
st.session_state.setdefault("coach_text", "")
st.session_state.setdefault("challenge_text", "")

with st.sidebar:
    st.header("🤖 AI Coach")
    api_key = get_secret_key()
    if api_key:
        st.caption("✅ Using GROQ_API_KEY from secrets.")
    else:
        api_key = st.text_input("Groq API key", type="password", placeholder="gsk_...").strip()
        st.caption("Stored only for this session. Game works without it.")

    st.subheader("Commentary")
    st.caption("Copy your score from the game HUD, then ask the coach.")
    score = st.number_input("Current score", min_value=0, value=0, step=50)
    status = st.selectbox("Game status", ["Playing", "Just won", "Just lost", "Stuck on a hard board"])
    mode = st.selectbox("Coach style", ["Hype announcer", "Strategy tip", "Post-game analysis"])

    if st.button("Get commentary", use_container_width=True):
        with st.spinner("Coach is thinking..."):
            text, err = ask_groq(
                api_key,
                "You are a witty, energetic arcade announcer for a neon bubble shooter. "
                "Reply in at most 3 short sentences. No markdown.",
                f"Style: {mode}. Player score: {score}. Status: {status}.",
            )
        st.session_state.coach_text = text or f"{err}\n\nOffline tip: {random.choice(OFFLINE_TIPS)}"

    if st.session_state.coach_text:
        st.markdown(f'<div class="glass">{st.session_state.coach_text}</div>', unsafe_allow_html=True)

    st.divider()
    st.subheader("Challenge generator")
    theme = st.text_input("Theme (optional)", placeholder="e.g. deep sea, cyberpunk, candy")
    if st.button("Generate challenge", use_container_width=True):
        with st.spinner("Designing a challenge..."):
            text, err = ask_groq(
                api_key,
                "You design short challenges for a bubble shooter game. Output exactly: "
                "a catchy title, a one-line goal the player can self-check (score, combo or "
                "shot limit), and one power-up style tip. Max 60 words. No markdown.",
                f"Theme: {theme or 'surprise me'}.",
            )
        st.session_state.challenge_text = text or f"{err}\n\nOffline challenge: Clear the board using bank shots only."

    if st.session_state.challenge_text:
        st.markdown(f'<div class="glass">{st.session_state.challenge_text}</div>', unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Game (HTML5 Canvas + vanilla JS, fully self-contained)
# ---------------------------------------------------------------------------
GAME_HTML = r"""
<!DOCTYPE html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
  *{box-sizing:border-box}
  html,body{margin:0;height:100%;overflow:hidden;background:transparent;
    font-family:"Trebuchet MS","Segoe UI",sans-serif;color:#eaf0ff;user-select:none}
  #app{height:100%;display:flex;flex-direction:column;align-items:center;gap:8px;padding:6px}
  #hud{display:flex;gap:8px;width:100%;max-width:520px;justify-content:center;flex:none}
  .chip{flex:1;background:rgba(255,255,255,.07);border:1px solid rgba(255,255,255,.16);
    backdrop-filter:blur(8px);border-radius:12px;padding:5px 8px;text-align:center;min-width:0}
  .chip small{display:block;font-size:10px;opacity:.65;letter-spacing:.04em}
  .chip b{font-size:17px;color:#7df9ff;text-shadow:0 0 10px rgba(125,249,255,.6)}
  #stage{position:relative;flex:none;border-radius:16px;overflow:hidden;
    box-shadow:0 0 0 1px rgba(140,160,255,.35),0 0 40px rgba(120,80,255,.35)}
  canvas{display:block;touch-action:none;cursor:crosshair}
  #ov{position:absolute;inset:0;display:none;flex-direction:column;align-items:center;
    justify-content:center;gap:10px;background:rgba(8,10,28,.72);backdrop-filter:blur(6px);text-align:center;padding:20px}
  #ov h2{margin:0;font-size:34px;color:#fff;text-shadow:0 0 18px #a78bfa}
  #ov p{margin:0;opacity:.85}
  #pa{margin-top:8px;border:0;border-radius:999px;padding:12px 30px;font-size:16px;font-weight:700;
    color:#0a0d22;background:linear-gradient(135deg,#7df9ff,#a78bfa);cursor:pointer;
    box-shadow:0 0 24px rgba(125,249,255,.55)}
  #pa:hover{filter:brightness(1.1)}
  #pa:focus-visible{outline:3px solid #fff;outline-offset:3px}
</style></head>
<body><div id="app">
  <div id="hud">
    <div class="chip"><small>SCORE</small><b id="sc">0</b></div>
    <div class="chip"><small>COMBO</small><b id="cb">x1</b></div>
    <div class="chip"><small>LEVEL</small><b id="lv">1</b></div>
    <div class="chip"><small>NEXT ROW</small><b id="nr">8</b></div>
    <div class="chip"><small>BEST</small><b id="bs">0</b></div>
  </div>
  <div id="stage"><canvas id="c"></canvas>
    <div id="ov"><h2 id="ot"></h2><p id="om"></p><button id="pa">Play Again</button></div>
  </div>
</div>
<script>
(()=>{
const R=20,COLS=10,W=COLS*2*R+R,H=640,RH=R*Math.sqrt(3),LIMIT=11,MAXR=13;
const SX=W/2,SY=H-52,SPEED=900;
const PAL=['#ff4d8d','#22d3ee','#a3e635','#fbbf24','#a78bfa','#3b82f6'];
const cv=document.getElementById('c'),ctx=cv.getContext('2d');
const DPR=Math.min(window.devicePixelRatio||1,2);
cv.width=W*DPR;cv.height=H*DPR;ctx.setTransform(DPR,0,0,DPR,0,0);
const $=id=>document.getElementById(id);

function tint(hex,amt){const n=parseInt(hex.slice(1),16);let r=n>>16,g=(n>>8)&255,b=n&255;
  const t=amt<0?0:255,p=Math.abs(amt);
  r=Math.round((t-r)*p+r);g=Math.round((t-g)*p+g);b=Math.round((t-b)*p+b);return `rgb(${r},${g},${b})`;}
const SKIN=PAL.map(c=>({l:tint(c,.6),m:c,d:tint(c,-.5)}));

let grid,shift,cur,nxt,proj,drops,parts,texts,score,combo,shots,level,state,aim,shake,best=0,last=0,mx=SX,my=0;
try{best=+localStorage.getItem('neonpop_best')||0}catch(e){}

const off=r=>(r+shift)&1;
const cx=(r,c)=>R+c*2*R+off(r)*R;
const cy=r=>R+r*RH;
const ncol=()=>Math.min(6,3+level);
const interval=()=>Math.max(3,9-level);
function present(){const s=new Set();for(const row of grid)for(const v of row)if(v>=0)s.add(v);return [...s];}
function pick(){const p=present();return p.length?p[Math.floor(Math.random()*p.length)]:Math.floor(Math.random()*ncol());}
function count(){let n=0;for(const row of grid)for(const v of row)if(v>=0)n++;return n;}

function reset(){
  grid=[];for(let r=0;r<MAXR;r++)grid.push(Array(COLS).fill(-1));
  shift=0;score=0;combo=0;shots=0;level=1;state='play';proj=null;drops=[];parts=[];texts=[];shake=0;
  for(let r=0;r<5;r++)for(let c=0;c<COLS;c++)grid[r][c]=Math.floor(Math.random()*ncol());
  cur=pick();nxt=pick();aim=-Math.PI/2;
  $('ov').style.display='none';hud();
}
function hud(){
  $('sc').textContent=score;$('cb').textContent='x'+Math.max(1,combo);$('lv').textContent=level;
  $('nr').textContent=interval()-(shots%interval());$('bs').textContent=best;
}
function nb(r,c){
  const o=off(r),L=[[r,c-1],[r,c+1]];
  if(o)L.push([r-1,c],[r-1,c+1],[r+1,c],[r+1,c+1]);else L.push([r-1,c-1],[r-1,c],[r+1,c-1],[r+1,c]);
  return L.filter(([a,b])=>a>=0&&a<MAXR&&b>=0&&b<COLS);
}
function match(r,c){
  const col=grid[r][c],seen=new Set([r*COLS+c]),q=[[r,c]],out=[];
  while(q.length){const [a,b]=q.pop();out.push([a,b]);
    for(const [x,y] of nb(a,b)){const k=x*COLS+y;if(!seen.has(k)&&grid[x][y]===col){seen.add(k);q.push([x,y]);}}}
  return out;
}
function floaters(){
  const seen=new Set(),q=[];
  for(let c=0;c<COLS;c++)if(grid[0][c]>=0){seen.add(c);q.push([0,c]);}
  while(q.length){const [a,b]=q.pop();
    for(const [x,y] of nb(a,b)){const k=x*COLS+y;if(!seen.has(k)&&grid[x][y]>=0){seen.add(k);q.push([x,y]);}}}
  const out=[];
  for(let r=0;r<MAXR;r++)for(let c=0;c<COLS;c++)if(grid[r][c]>=0&&!seen.has(r*COLS+c))out.push([r,c]);
  return out;
}
function burst(x,y,col){
  for(let i=0;i<10;i++){const a=Math.random()*6.283,s=80+Math.random()*220;
    parts.push({x,y,vx:Math.cos(a)*s,vy:Math.sin(a)*s,life:.6+Math.random()*.4,max:1,col,r:2+Math.random()*3});}
}
function addRow(){
  const row=[];for(let c=0;c<COLS;c++)row.push(Math.floor(Math.random()*ncol()));
  grid.unshift(row);grid.pop();shift^=1;shake=8;
}
function land(){
  let best_=null,bd=1e9;
  for(let r=0;r<MAXR;r++)for(let c=0;c<COLS;c++){
    if(grid[r][c]>=0)continue;
    const d=Math.hypot(cx(r,c)-proj.x,cy(r)-proj.y);if(d<bd){bd=d;best_=[r,c];}
  }
  const [r,c]=best_;grid[r][c]=proj.col;proj=null;
  const grp=match(r,c);
  if(grp.length>=3){
    combo++;let pts=grp.length*10*combo;
    for(const [a,b] of grp){burst(cx(a,b),cy(a),grid[a][b]);grid[a][b]=-1;}
    const fl=floaters();
    for(const [a,b] of fl){drops.push({x:cx(a,b),y:cy(a),vx:(Math.random()-.5)*120,vy:-60,col:grid[a][b],a:1});grid[a][b]=-1;}
    if(fl.length)pts+=fl.length*30*combo;
    score+=pts;
    texts.push({x:cx(r,c),y:cy(r),t:'+'+pts+(fl.length?' DROP!':''),life:1});
    level=1+Math.floor(score/1500);
  }else combo=0;
  shots++;
  if(count()===0){score+=500;finish('win');return;}
  if(shots%interval()===0)addRow();
  for(let rr=LIMIT;rr<MAXR;rr++)if(grid[rr].some(v=>v>=0)){finish('lose');return;}
  cur=nxt;nxt=pick();hud();
}
function finish(s){
  state=s;if(score>best){best=score;try{localStorage.setItem('neonpop_best',best)}catch(e){}}
  hud();
  $('ot').textContent=s==='win'?'Board cleared!':'Game over';
  $('om').textContent='Final score '+score+(s==='win'?' (includes 500 clear bonus)':'. Bubbles crossed the line.');
  $('ov').style.display='flex';
}
function fire(){
  if(proj||state!=='play')return;
  proj={x:SX,y:SY,vx:Math.cos(aim)*SPEED,vy:Math.sin(aim)*SPEED,col:cur};
}
function swap(){if(proj||state!=='play')return;const t=cur;cur=nxt;nxt=t;}

function hitsBubble(x,y){
  const r0=Math.round((y-R)/RH);
  for(let r=Math.max(0,r0-1);r<=Math.min(MAXR-1,r0+1);r++)for(let c=0;c<COLS;c++)
    if(grid[r][c]>=0&&Math.hypot(cx(r,c)-x,cy(r)-y)<R*1.85)return true;
  return false;
}
function update(dt){
  if(proj){
    const steps=Math.ceil(SPEED*dt/6);
    for(let i=0;i<steps&&proj;i++){
      proj.x+=proj.vx*dt/steps;proj.y+=proj.vy*dt/steps;
      if(proj.x<R){proj.x=R;proj.vx=Math.abs(proj.vx);}
      if(proj.x>W-R){proj.x=W-R;proj.vx=-Math.abs(proj.vx);}
      if(proj.y<=R||hitsBubble(proj.x,proj.y)){if(proj.y<R)proj.y=R;land();}
    }
  }
  for(const p of parts){p.x+=p.vx*dt;p.y+=p.vy*dt;p.vy+=400*dt;p.life-=dt;}
  parts=parts.filter(p=>p.life>0);
  for(const d of drops){d.x+=d.vx*dt;d.y+=d.vy*dt;d.vy+=1500*dt;d.a=Math.max(0,d.a-dt*.6);}
  drops=drops.filter(d=>d.y<H+40&&d.a>0);
  for(const t of texts){t.y-=40*dt;t.life-=dt;}
  texts=texts.filter(t=>t.life>0);
  shake*=Math.pow(.001,dt);
}

function bubble(x,y,i,a=1,r=R){
  const s=SKIN[i];ctx.globalAlpha=a;
  const g=ctx.createRadialGradient(x-r*.35,y-r*.4,r*.1,x,y,r);
  g.addColorStop(0,s.l);g.addColorStop(.55,s.m);g.addColorStop(1,s.d);
  ctx.fillStyle=g;ctx.beginPath();ctx.arc(x,y,r-1,0,6.283);ctx.fill();
  ctx.strokeStyle='rgba(255,255,255,.28)';ctx.lineWidth=1;ctx.stroke();
  ctx.fillStyle='rgba(255,255,255,.7)';ctx.beginPath();
  ctx.ellipse(x-r*.3,y-r*.45,r*.3,r*.15,-.6,0,6.283);ctx.fill();
  ctx.globalAlpha=1;
}
function trajectory(){
  let x=SX,y=SY,vx=Math.cos(aim),vy=Math.sin(aim),d=0;
  ctx.fillStyle='rgba(255,255,255,.75)';
  for(let i=0;i<420;i++){
    x+=vx*4;y+=vy*4;
    if(x<R){x=R;vx=Math.abs(vx);}
    if(x>W-R){x=W-R;vx=-Math.abs(vx);}
    if(y<=R||hitsBubble(x,y))break;
    d+=4;if(d%20===0){ctx.beginPath();ctx.arc(x,y,2.2,0,6.283);ctx.fill();}
  }
}
function draw(t){
  ctx.save();ctx.clearRect(0,0,W,H);
  if(shake>.3)ctx.translate((Math.random()-.5)*shake,(Math.random()-.5)*shake);
  const bg=ctx.createLinearGradient(0,0,0,H);bg.addColorStop(0,'#0c1030');bg.addColorStop(1,'#1c0f40');
  ctx.fillStyle=bg;ctx.fillRect(-10,-10,W+20,H+20);
  ctx.strokeStyle='rgba(125,249,255,.05)';ctx.lineWidth=1;
  for(let x=0;x<W;x+=40){ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,H);ctx.stroke();}
  // danger line (pulses when the stack is close)
  const dy=cy(LIMIT)-R;let near=false;
  for(let r=LIMIT-2;r<LIMIT;r++)if(grid[r].some(v=>v>=0))near=true;
  ctx.setLineDash([10,8]);ctx.lineWidth=2;
  ctx.strokeStyle=near?`rgba(255,70,100,${.55+.4*Math.sin(t/120)})`:'rgba(255,70,100,.4)';
  ctx.beginPath();ctx.moveTo(0,dy);ctx.lineTo(W,dy);ctx.stroke();ctx.setLineDash([]);
  for(let r=0;r<MAXR;r++)for(let c=0;c<COLS;c++)if(grid[r][c]>=0)bubble(cx(r,c),cy(r),grid[r][c]);
  for(const d of drops)bubble(d.x,d.y,d.col,d.a);
  for(const p of parts){ctx.globalAlpha=Math.max(0,p.life);ctx.fillStyle=SKIN[p.col].m;
    ctx.beginPath();ctx.arc(p.x,p.y,p.r,0,6.283);ctx.fill();}
  ctx.globalAlpha=1;
  if(state==='play'&&!proj)trajectory();
  if(proj){ctx.shadowColor=SKIN[proj.col].m;ctx.shadowBlur=18;bubble(proj.x,proj.y,proj.col);ctx.shadowBlur=0;}
  // shooter base
  ctx.fillStyle='rgba(255,255,255,.08)';ctx.beginPath();ctx.arc(SX,SY,R+10,0,6.283);ctx.fill();
  ctx.strokeStyle='rgba(125,249,255,.5)';ctx.lineWidth=2;ctx.stroke();
  if(!proj&&state==='play')bubble(SX,SY,cur);
  ctx.fillStyle='rgba(255,255,255,.6)';ctx.font='11px sans-serif';ctx.textAlign='center';
  ctx.fillText('NEXT (tap / Space)',SX-92,SY+34);
  bubble(SX-92,SY+8,nxt,1,R*.7);
  ctx.font='bold 16px sans-serif';
  for(const f of texts){ctx.globalAlpha=Math.min(1,f.life*1.5);ctx.fillStyle='#fff';ctx.fillText(f.t,f.x,f.y);}
  ctx.globalAlpha=1;ctx.restore();
}

function loop(ts){
  const dt=Math.min(.033,(ts-last)/1000||0);last=ts;
  update(dt);
  draw(ts);requestAnimationFrame(loop);
}

function pos(e){const b=cv.getBoundingClientRect();return [(e.clientX-b.left)*W/b.width,(e.clientY-b.top)*H/b.height];}
function setAim(e){
  const [x,y]=pos(e);mx=x;my=y;
  let a=Math.atan2(Math.min(y-SY,-10),x-SX);
  aim=Math.max(-Math.PI+.2,Math.min(-.2,a));
}
cv.addEventListener('pointermove',setAim);
cv.addEventListener('pointerdown',setAim);
cv.addEventListener('pointerup',e=>{
  setAim(e);const [x,y]=pos(e);
  if(Math.hypot(x-(SX-92),y-(SY+8))<28)swap();else fire();
});
window.addEventListener('keydown',e=>{
  if(e.code==='Space'){e.preventDefault();swap();}
  if((e.code==='Enter'||e.code==='KeyR')&&state!=='play')reset();
});
$('pa').addEventListener('click',reset);

function fit(){
  const hh=$('hud').offsetHeight+22;
  const s=Math.min((window.innerWidth-12)/W,(window.innerHeight-hh)/H);
  cv.style.width=Math.floor(W*s)+'px';cv.style.height=Math.floor(H*s)+'px';
}
window.addEventListener('resize',fit);
reset();fit();requestAnimationFrame(loop);
})();
</script></body></html>
"""

st.title("🫧 Neon Pop AI")
st.caption("Aim with the mouse or finger, tap to shoot. Match 3+ to pop; cut clusters loose for drop bonuses.")
components.html(GAME_HTML, height=800, scrolling=False)
