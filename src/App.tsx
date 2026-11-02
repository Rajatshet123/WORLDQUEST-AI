import { useEffect, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { Activity, ArrowDownRight, ArrowUpRight, AudioLines, Bell, BookOpen, Check, ChevronDown, CircleHelp, Crown, Eye, Flame, Gamepad2, Heart, Link2, MessageCircle, MoreHorizontal, ScrollText, Settings2, Shield, Swords, Users, WandSparkles } from 'lucide-react'

type Event = { user: string; action: string; color: string; time: string }
type BackendConnection = 'connecting' | 'connected' | 'disconnected'
const initialEvents: Event[] = [
  { user: 'moonlitmira', action: 'joined the expedition', color: '#d8a7ff', time: 'now' },
  { user: 'Frostbyte', action: 'casts Frost Nova ✦', color: '#80c9ff', time: '12s' },
  { user: 'EmberWarden', action: 'dealt 184 damage to Malachar', color: '#ff986b', time: '24s' },
  { user: 'pixelprophet', action: 'voted for The Ashen Gate', color: '#b4e483', time: '31s' },
  { user: 'LunaByte', action: 'healed the party for 35 HP', color: '#f58cbe', time: '48s' },
]
const players = [{name:'EmberWarden',class:'Spellblade',level:18,xp:2840,color:'#ff966e',icon:'✦'}, {name:'Frostbyte',class:'Frost mage',level:16,xp:2310,color:'#80c9ff',icon:'❄'}, {name:'LunaByte',class:'Moon cleric',level:14,xp:1890,color:'#d7a0ff',icon:'☾'}, {name:'pixelprophet',class:'Ranger',level:12,xp:1420,color:'#b1df78',icon:'⌁'}]
const API = import.meta.env.VITE_API_URL || 'http://localhost:8000'
function App() {
  const [hp, setHp] = useState(68)
  const [votes, setVotes] = useState([24, 18])
  const [events, setEvents] = useState(initialEvents)
  const [joined, setJoined] = useState(true)
  const [tab, setTab] = useState('Overview')
  const [twitchConnected, setTwitchConnected] = useState(false)
  const [questTitle, setQuestTitle] = useState('The Shards of Mourning')
  const [backendConnection, setBackendConnection] = useState<BackendConnection>('connecting')
  const [worldStateReady, setWorldStateReady] = useState(false)
  useEffect(() => {
    let socket: WebSocket | undefined
    fetch(`${API}/api/state`).then(r => r.ok ? r.json() : null).then(data => {
      if (!data) {
        setBackendConnection('disconnected')
        return
      }
      setTwitchConnected(Boolean(data.twitch?.connected))
      setHp(data.boss_hp ?? 68)
      setVotes([data.votes?.['1'] ?? 0, data.votes?.['2'] ?? 0])
      if (data.quest?.title) setQuestTitle(data.quest.title)
      if (data.events?.length) setEvents(data.events.map((e: any) => ({user:e.user,action:e.action,color:e.source==='twitch'?'#91d9b8':'#bd9bff',time:'now'})))
      setWorldStateReady(true)
      setBackendConnection('connected')
    }).catch(() => setBackendConnection('disconnected'))
    try {
      socket = new WebSocket(`${API.replace(/^http/, 'ws')}/ws`)
      socket.onmessage = event => {
        const data = JSON.parse(event.data)
        if (!data.state) return
        setHp(data.state.boss_hp)
        setVotes([data.state.votes?.['1'] ?? 0, data.state.votes?.['2'] ?? 0])
        if (data.state.quest?.title) setQuestTitle(data.state.quest.title)
        setTwitchConnected(Boolean(data.state.twitch?.connected))
        if (data.event?.user) setEvents(e => [{user:data.event.user,action:data.event.action,color:data.event.source==='twitch'?'#91d9b8':'#bd9bff',time:'now'},...e.slice(0,5)])
        setWorldStateReady(true)
        setBackendConnection('connected')
      }
      socket.onerror = () => setBackendConnection('disconnected')
      socket.onclose = () => setBackendConnection('disconnected')
    } catch { setBackendConnection('disconnected') }
    return () => socket?.close()
  }, [])
  const addEvent = (user: string, action: string, color = '#bd9bff') => setEvents(e => [{user, action, color, time:'now'}, ...e.slice(0, 5)])
  const sendDemoCommand = (message: string) => { fetch(`${API}/api/demo/event`, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:'DemoHero',message})}).catch(() => undefined) }
  const attack = () => { setHp(v => Math.max(0, v - 3)); addEvent('You', 'rally the party — 240 damage!', '#e4bb79'); sendDemoCommand('!attack') }
  const vote = (i: number) => { setVotes(v => v.map((n, j) => j === i ? n + 1 : n)); addEvent('You', `voted for ${i ? 'The Hollow Crown' : 'The Ashen Gate'}`, '#9de0c1'); sendDemoCommand(`!vote ${i+1}`) }
  const act = (name: string) => { if (name === 'join') { setJoined(v => !v); addEvent('You', joined ? 'left the expedition' : 'joined the expedition', '#d8a7ff'); if (!joined) sendDemoCommand('!join') } else if (name === 'heal') { setHp(v => Math.min(100, v + 1)); addEvent('You', 'used a healing potion ✦', '#f58cbe'); sendDemoCommand('!heal') } else if (name === 'quest') { addEvent('Worldkeeper', 'A new quest has been revealed', '#b8a0ff'); fetch(`${API}/api/story`, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({prompt:'Generate the next quest for the current world.'})}).catch(() => undefined) } else { addEvent('You', 'checked your adventurer status', '#9ea6bd'); sendDemoCommand('!status') } }
  if (window.location.pathname === '/overlay') return <Overlay hp={worldStateReady ? hp : null} quest={worldStateReady ? (votes[0] >= votes[1] ? 'The Ashen Gate' : 'The Hollow Crown') : null} connection={backendConnection} />
  const totalVotes = votes[0] + votes[1]
  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark"><WandSparkles size={18}/></div><div><strong>WORLDQUEST</strong><span>WORLD ENGINE <i>✦</i></span></div></div>
      <div className="channel"><div className="channel-avatar">S</div><div className="channel-meta"><b>{twitchConnected ? 'Twitch channel' : 'Demo channel'}</b><span><span className={twitchConnected ? 'live-dot' : 'status-dot'}/>{twitchConnected ? ' CONNECTED' : ' LOCAL PREVIEW'}</span></div><ChevronDown size={15} className="muted"/></div>
      <div className="side-label">CREATOR STUDIO</div>
      <nav>{[['Overview',Activity],['World builder',BookOpen],['Quest journal',ScrollText],['Community',Users],['OBS overlay',Eye]].map(([label, Icon]: any) => <button key={label} className={`nav-item ${tab===label?'active':''}`} onClick={() => setTab(label)}><Icon size={17}/>{label}{label==='Community'&&<span className="nav-count">12</span>}</button>)}</nav>
      <div className="side-label world-label">YOUR WORLD <button aria-label="World options"><MoreHorizontal size={16}/></button></div>
      <div className="world-card"><div className="world-thumb"><div className="thumb-moon"/><span>✧</span><div className="thumb-mountains"/></div><div className="world-info"><b>Veyra, the Lost Realm</b><span><span className="status-dot"/> World is active</span></div><button className="icon-btn"><MoreHorizontal size={16}/></button></div>
      <div className="side-spacer"/>
      <div className="storage"><div><span>WORLD MEMORY</span><b>68%</b></div><div className="storage-track"><i/></div><small>12,480 / 18,000 events</small></div>
      <button className="profile"><div className="profile-avatar">JD</div><span><b>Jamie Davis</b><small>Creator account</small></span><MoreHorizontal size={17}/></button>
    </aside>
    <main className="main-area">
      <header className="topbar"><div className="breadcrumbs"><span>Creator studio</span><b>/</b><strong>{tab}</strong></div><div className="top-actions"><div className="demo-pill"><span/> {twitchConnected ? 'TWITCH CONNECTED' : 'LOCAL DEMO MODE'} <CircleHelp size={13}/></div>{!twitchConnected && <a className="connect-btn" href={`${API}/auth/twitch`}>Connect Twitch</a>}<button className="top-icon" title="Notifications"><Bell size={17}/><i/></button><button className="top-icon"><Settings2 size={17}/></button><button className="help-btn"><CircleHelp size={15}/> Help center</button></div></header>
      <div className="content">
        <section className="page-heading"><div><div className="eyebrow"><span className="pulse-dot"/> WORLD STATUS <span className="eyebrow-divider">/</span> <span className="gold">CHAPTER III · THE SHATTERED VEIL</span></div><h1>Your world is <em>alive.</em></h1><p>Your community has shaped 148 moments in Veyra this week. Here’s what’s unfolding.</p></div><div className="heading-actions"><a className="outline-btn link-btn" href="/overlay" target="_blank" rel="noreferrer"><Eye size={15}/> Preview overlay</a><button className="primary-btn" onClick={() => act('quest')}><WandSparkles size={15}/> Generate story event</button></div></section>
        <section className="stats-grid"><Stat icon={Users} label="ADVENTURERS" value="1,284" delta="12.8%" up/><Stat icon={Flame} label="WORLD ACTIVITY" value="86.4%" delta="8.2%" up/><Stat icon={Swords} label="BOSSES DEFEATED" value="27" delta="This season"/><Stat icon={Heart} label="COMMUNITY VOTES" value="3,891" delta="24.6%" up/></section>
        <section className="dashboard-grid">
          <div className="left-column">
            <article className="panel world-panel"><div className="panel-head"><div><div className="panel-kicker"><span className="live-dot"/> LIVE WORLD</div><h2>Veyra, the Lost Realm</h2><p>Chapter III · The Shattered Veil</p></div><button className="icon-btn"><MoreHorizontal size={18}/></button></div>
              <div className="world-scene"><div className="scene-grain"/><div className="moon-glow"/><div className="scene-stars">✦　 ·　　 ✧　　 ·　 ✦　　　 ·</div><div className="scene-sigil">ᛟ</div><div className="scene-mountain far"/><div className="scene-mountain mid"/><div className="scene-mountain near"/><div className="scene-ruin">⌜　⌝<br/>╱▥╲</div><div className="scene-copy"><span>THE VEIL IS THINNING</span><b>Something stirs<br/>beneath the ash.</b><small>World event · 2 minutes ago</small></div><div className="scene-location"><span>◈</span> THE ASHEN WILDS <i>·</i> ZONE 04</div><div className="scene-time">DAY 28 <span>·</span> DUSK</div><div className="scene-fog"/></div>
              <div className="boss-row"><div className="boss-emblem"><Shield size={20}/></div><div className="boss-info"><div className="boss-title"><div><span>WORLD BOSS</span><b>Malachar, the Hollow King</b></div><div className="hp-value"><Heart size={13}/> {hp}% <small>HP</small></div></div><div className="hp-track"><motion.i animate={{width:`${hp}%`}} transition={{duration:.7}}/></div><div className="hp-foot"><span>Tier IV · Ancient Wraith</span><span>{Math.round(14500 * hp / 100).toLocaleString()} / 14,500 HP</span></div></div><button className="attack-btn" onClick={attack}><Swords size={15}/> Rally attack</button></div>
              <div className="panel-foot"><div className="avatars"><span style={{background:'#57445c'}}>E</span><span style={{background:'#324a5d'}}>F</span><span style={{background:'#664453'}}>L</span><span style={{background:'#4e583c'}}>p</span><span className="avatar-more">+128</span></div><span className="foot-muted"><span className="live-dot"/> 132 adventurers in battle</span><button className="text-btn" onClick={() => setTab('Community')}>View battle <ArrowUpRight size={14}/></button></div>
            </article>
            <article className="panel quest-panel"><div className="section-heading"><div><div className="panel-kicker">COMMUNITY QUEST</div><h2>{questTitle}</h2><p>The Veil fractures. Choose where the party ventures next.</p></div><span className="voting-tag"><span className="pulse-dot"/> VOTING LIVE</span></div><div className="quest-options">{[{title:'The Ashen Gate',desc:'Descend into the forgotten catacombs.',pct:totalVotes?Math.round(votes[0]/totalVotes*100):0,votes:votes[0],symbol:'ᛟ',tone:'amber'},{title:'The Hollow Crown',desc:'Hunt the wraith through the mist.',pct:totalVotes?Math.round(votes[1]/totalVotes*100):0,votes:votes[1],symbol:'♧',tone:'violet'}].map((o,i)=><button className="quest-option" onClick={() => vote(i)} key={o.title}><div className={`quest-icon ${o.tone}`}>{o.symbol}</div><div className="quest-detail"><div className="quest-choice">OPTION {i+1}<span>{o.votes} votes</span></div><b>{o.title}</b><small>{o.desc}</small><div className="vote-track"><motion.i animate={{width:`${o.pct}%`}} transition={{duration:.5}} className={o.tone}/></div></div><strong className="vote-pct">{o.pct}%</strong></button>)}</div><div className="quest-foot"><span><Users size={14}/> {totalVotes} votes · Ends in 04:32</span><span>Votes are cast by chat with <code>!vote 1</code> or <code>!vote 2</code></span></div></article>
          </div>
          <div className="right-column">
            <article className="panel events-panel"><div className="right-panel-head"><div><div className="panel-kicker"><span className="pulse-dot"/> LIVE ACTIVITY</div><h2>World events</h2></div><button className="icon-btn"><MoreHorizontal size={18}/></button></div><div className="event-list"><AnimatePresence initial={false}>{events.map(e=><motion.div key={`${e.user}-${e.action}`} className="event" initial={{opacity:0,y:-8}} animate={{opacity:1,y:0}} exit={{opacity:0,height:0}} transition={{duration:.24}}><div className="event-avatar" style={{color:e.color,background:`${e.color}18`}}>{e.user.slice(0,1).toUpperCase()}</div><div className="event-copy"><b style={{color:e.color}}>{e.user}</b> <span>{e.action}</span><small>{e.time === 'now' ? 'Just now' : `${e.time} ago`}</small></div></motion.div>)}</AnimatePresence></div><div className="chat-composer"><MessageCircle size={14}/><span>Chat activity appears here...</span><AudioLines size={15}/></div><div className="demo-note"><span className="demo-note-icon">i</span><span>Local demo activity <b>is simulated</b> and is not real Twitch chat.</span></div></article>
            <article className="panel leaderboard-panel"><div className="right-panel-head"><div><div className="panel-kicker">THIS WEEK</div><h2>Top adventurers</h2></div><button className="text-btn" onClick={() => setTab('Community')}>View all <ArrowUpRight size={14}/></button></div><div className="leader-list">{players.map((p,i)=><div className="leader" key={p.name}><span className={`rank ${i===0?'first':''}`}>{i===0?<Crown size={13}/>:`0${i+1}`}</span><div className="leader-avatar" style={{color:p.color,background:`${p.color}19`}}>{p.icon}</div><div className="leader-name"><b>{p.name}</b><small>{p.class} · Lv. {p.level}</small></div><div className="leader-xp"><b>{p.xp.toLocaleString()}</b><small>XP</small></div></div>)}</div><button className="leader-footer" onClick={() => setTab('Community')}>See all adventurers <ArrowDownRight size={14}/></button></article>
            <article className="panel commands-panel"><div className="right-panel-head"><div><div className="panel-kicker">CHAT COMMANDS</div><h2>Play from chat</h2></div><Gamepad2 size={17} className="muted"/></div><div className="command-list"><button onClick={() => act('join')}><code>!join</code><span>Join the adventure</span></button><button onClick={() => act('status')}><code>!status</code><span>Check your stats</span></button><button onClick={() => act('quest')}><code>!quest</code><span>See current quest</span></button><button onClick={() => act('heal')}><code>!heal</code><span>Use a healing potion</span></button></div><div className="commands-footer"><span><Check size={13}/> All systems operational</span><a className="overlay-link" href="/overlay" target="_blank" rel="noreferrer"><Link2 size={13}/> Overlay link</a></div></article>
          </div>
        </section>
        <footer className="page-footer"><span><span className="status-dot"/> WORLD ENGINE RUNNING <i>·</i> LAST SAVED JUST NOW</span><span>WORLDQUEST AI <i>·</i> BUILD 0.1.0</span></footer>
      </div>
    </main>
  </div>
}
function Stat({icon:Icon,label,value,delta,up}:any){return <article className="stat-card"><div className="stat-top"><span className="stat-icon"><Icon size={16}/></span><span className="stat-label">{label}</span><button><MoreHorizontal size={17}/></button></div><div className="stat-value">{value}</div><div className={`stat-delta ${up?'positive':''}`}>{up?<ArrowUpRight size={13}/>:null}{delta}{up?<span> vs last week</span>:null}</div></article>}
function Overlay({hp,quest,connection}:{hp:number|null;quest:string|null;connection:BackendConnection}){const ready=hp!==null&&quest!==null;const label=connection==='connected'?'WORLD ENGINE CONNECTED':connection==='connecting'?'CONNECTING…':'WORLD ENGINE DISCONNECTED';return <main className="obs-overlay"><div className="overlay-top"><span>✦ WORLDQUEST</span><span>CHAPTER III · THE SHATTERED VEIL</span></div><div className="overlay-content"><span className="overlay-kicker">WORLD BOSS · TIER IV</span><h1>Malachar, the Hollow King</h1>{ready?<><div className="overlay-hp"><motion.i animate={{width:`${hp}%`}}/><b>{hp}%</b></div><div className="overlay-bottom"><span><Swords size={15}/> {Math.round(14500*hp/100).toLocaleString()} / 14,500 HP</span><span>COMMUNITY QUEST · {quest}</span></div></>:<div className="overlay-pending"><span>{connection==='disconnected'?'World state unavailable':'Waiting for live world state…'}</span><i/></div>}</div><div className={`overlay-status ${connection}`}><span/> {label}</div></main>}
export default App
