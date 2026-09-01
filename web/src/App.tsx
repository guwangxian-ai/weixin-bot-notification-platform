import { useCallback, useEffect, useMemo, useState } from 'react'
import { Activity, BellRing, Bot, Building2, FileClock, LayoutDashboard, LogOut, Settings, Users, X } from 'lucide-react'

type Json = Record<string, unknown>
type NoticeSummary = { id: string; notification_type: 'binding_welcome' | 'manual_test' | 'business'; status: string; failure_code?: string; failure_message?: string; created_at: string }
type ManualTestState = { allowed: boolean; reason?: string; retry_after_seconds?: number; latest_delivery?: NoticeSummary | null }
type Binding = { status: string; account_id_masked: string; bound_at: string; health_status: string; last_health_at?: string; delivery_ready: boolean; welcome_delivery?: NoticeSummary | null; manual_test?: ManualTestState }
type BindingSession = { id: string; company_id: string; employee_id: string; status: string; expires_at: string; qr_image_url?: string; failure_code?: string }
type Employee = { id: string; company_id: string; name: string; department: string; content_vertical: string; account_name: string; status: string; binding: Binding | null; binding_session: BindingSession | null }
type Delivery = { id: string; status: string; employee_id: string; title: string; body: string; notification_type: 'binding_welcome' | 'manual_test' | 'business'; idempotency_key: string; retry_count: number; failure_code?: string; failure_message?: string; created_at: string }

const sections = [
  ['overview', '概览', LayoutDashboard], ['companies', '公司切换', Building2],
  ['employees', '用户管理', Users],
  ['deliveries', '通知日志', BellRing],
  ['bot', 'Bot 状态', Bot], ['logs', '操作日志', FileClock], ['settings', '系统设置', Settings],
] as const

async function api(path: string, options: RequestInit = {}) {
  const response = await fetch(`api/v1/${path}`, { credentials: 'same-origin', ...options, headers: { 'Content-Type': 'application/json', ...(options.headers || {}) } })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(data.detail || `请求失败 (${response.status})`)
  return data
}

export function App() {
  const [csrf, setCsrf] = useState('')
  const [section, setSection] = useState('overview')
  const [company, setCompany] = useState('greenhome')
  const [employees, setEmployees] = useState<Employee[]>([])
  const [deliveries, setDeliveries] = useState<Delivery[]>([])
  const [logs, setLogs] = useState<Json[]>([])
  const [bot, setBot] = useState<Json>({})
  const [bindingSession, setBindingSession] = useState<BindingSession | null>(null)
  const [error, setError] = useState('')
  const [login, setLogin] = useState({ username: '', password: '' })

  const refresh = useCallback(async () => {
    try {
      const [e, d, b, l] = await Promise.all([api(`employees?company_id=${company}`), api(`deliveries?company_id=${company}`), api('bot/health'), api(`audit-logs?company_id=${company}`)])
      setEmployees(e); setDeliveries(d); setBot(b); setLogs(l); setError('')
    } catch (err) { setError((err as Error).message) }
  }, [company])
  useEffect(() => { if (csrf) void refresh() }, [csrf, refresh])

  const stats = useMemo(() => ({
    employees: employees.filter(e => e.status === 'active').length,
    bound: employees.filter(e => e.binding).length,
    pending: deliveries.filter(d => ['pending', 'retrying', 'waiting_interaction'].includes(d.status)).length,
    confirmed: deliveries.filter(d => d.status === 'confirmed').length,
  }), [employees, deliveries])

  const submitLogin = async (event: React.FormEvent) => {
    event.preventDefault(); setError('')
    try { const data = await api('auth/login', { method: 'POST', body: JSON.stringify(login) }); setCsrf(data.csrf_token) }
    catch (err) { setError((err as Error).message) }
  }

  if (!csrf) return <main className="login-shell"><section className="login-card"><div className="brand-mark"><Bot size={27}/></div><p className="eyebrow">通用多租户通知平台</p><h1>微信 Bot 通知系统</h1><p className="muted">管理员登录后管理用户独立微信 Bot，并查看通知日志。</p><form onSubmit={submitLogin}><label>用户名<input autoComplete="username" value={login.username} onChange={e => setLogin({...login, username:e.target.value})}/></label><label>密码<input type="password" autoComplete="current-password" value={login.password} onChange={e => setLogin({...login, password:e.target.value})}/></label>{error && <p className="error">{error}</p>}<button className="primary" type="submit">安全登录</button></form></section></main>

  return <div className="app-shell">
    <aside><div className="brand"><div className="brand-mark"><Bot size={22}/></div><div><strong>微信 Bot 通知系统</strong><small>Weixin notification</small></div></div><nav>{sections.map(([id,label,Icon]) => <button key={id} className={section===id?'active':''} onClick={()=>setSection(id)}><Icon size={18}/>{label}</button>)}</nav><button className="logout" onClick={()=>{void api('auth/logout',{method:'POST'});setCsrf('')}}><LogOut size={17}/>退出登录</button></aside>
    <main className="workspace"><header><div><p className="eyebrow">员工微信通知工作台</p><h2>{sections.find(s=>s[0]===section)?.[1]}</h2></div><div className="header-actions"><select value={company} onChange={e=>setCompany(e.target.value)}><option value="greenhome">绿色家装饰</option><option value="sanlin">三林装饰</option></select><button className="ghost" onClick={()=>void refresh()}><Activity size={16}/>刷新</button></div></header>{error&&<div className="alert">{error}</div>}<Content section={section} company={company} csrf={csrf} employees={employees} deliveries={deliveries} logs={logs} bot={bot} stats={stats} refresh={refresh} openBinding={setBindingSession}/></main>
    {bindingSession && <BindingModal initial={bindingSession} csrf={csrf} onClose={()=>setBindingSession(null)} onChanged={refresh}/>}
  </div>
}

function Content({section,company,csrf,employees,deliveries,logs,bot,stats,refresh,openBinding}:{section:string;company:string;csrf:string;employees:Employee[];deliveries:Delivery[];logs:Json[];bot:Json;stats:Record<string,number>;refresh:()=>Promise<void>;openBinding:(session:BindingSession)=>void}) {
  if(section==='overview') return <><div className="stat-grid"><Stat label="在职员工" value={stats.employees}/><Stat label="已绑定微信 Bot" value={stats.bound}/><Stat label="待处理投递" value={stats.pending}/><Stat label="员工已确认" value={stats.confirmed}/></div><Panel title="近期投递"><DeliveryTable rows={deliveries.slice(0,8)}/></Panel></>
  if(section==='companies') return <Panel title="公司与租户隔离"><p>当前公司：<b>{company==='greenhome'?'绿色家装饰':'三林装饰'}</b></p><p className="muted">公司管理员只能访问所属 company_id；独立 Bot 与绑定会话同样受租户隔离。</p></Panel>
  if(section==='employees') return <EmployeePanel company={company} csrf={csrf} rows={employees} refresh={refresh} openBinding={openBinding}/>
  if(section==='deliveries') return <Panel title="通知日志"><DeliveryTable rows={deliveries}/></Panel>
  if(section==='bot') return <Panel title="员工独立微信 Bot"><div className="bot-state"><Bot size={38}/><div><b>{stats.bound ? `${stats.bound} 个员工 Bot 已绑定` : '等待员工扫码绑定'}</b><p className="muted">当前模式：{String(bot.mode||'dry-run')} · 真实发送：{bot.safe_to_send?'允许':'禁用'}。每次扫码产生独立 iLink Bot 身份，不复用管理 Bot。</p></div></div></Panel>
  if(section==='logs') return <Panel title="操作审计"><table><thead><tr><th>时间</th><th>动作</th><th>对象</th><th>公司</th></tr></thead><tbody>{logs.map((l,i)=><tr key={String(l.id||i)}><td>{String(l.created_at||'')}</td><td>{String(l.action||'')}</td><td>{String(l.target_type||'')} · {String(l.target_id||'')}</td><td>{String(l.company_id||'系统')}</td></tr>)}</tbody></table></Panel>
  return <Panel title="系统设置"><p>反向代理示例前缀：<code>/weixin-bot-notification-platform/</code></p><p>Bot 登录票据和凭据加密存储；API、页面和审计只显示状态与掩码。</p></Panel>
}


function EmployeePanel({company,csrf,rows,refresh,openBinding}:{company:string;csrf:string;rows:Employee[];refresh:()=>Promise<void>;openBinding:(session:BindingSession)=>void}) {
  const [open,setOpen]=useState(false)
  const [form,setForm]=useState({name:'',department:'',content_vertical:'',account_name:''})
  const [testSending,setTestSending]=useState('')
  const [testResults,setTestResults]=useState<Record<string,NoticeSummary>>({})
  const create=async(e:React.FormEvent)=>{e.preventDefault();const created=await api('employees',{method:'POST',headers:{'X-CSRF-Token':csrf},body:JSON.stringify({company_id:company,...form,target_platforms:['douyin'],secondary_topics:[],tone:'专业直接',video_duration_seconds:60,publishing_frequency:'每周3条'})});setOpen(false);setForm({name:'',department:'',content_vertical:'',account_name:''});await refresh();if(created.binding_session)openBinding(created.binding_session)}
  const generate=async(employee:Employee)=>{const session=await api(`employees/${employee.id}/binding-sessions`,{method:'POST',headers:{'X-CSRF-Token':csrf}});await refresh();openBinding(session)}
  const unbind=async(employee:Employee)=>{if(!window.confirm(`确认解除 ${employee.name} 的微信 Bot？后续投递会立即停止，历史记录保留。`))return;await api(`employees/${employee.id}/unbind`,{method:'POST',headers:{'X-CSRF-Token':csrf},body:JSON.stringify({confirm:true})});await refresh()}
  const transfer=async(source:Employee)=>{const targets=rows.filter(e=>e.id!==source.id&&e.status==='active'&&!e.binding);if(!targets.length){window.alert('没有可接收该 Bot 的在职未绑定员工');return}const targetId=window.prompt(`输入目标员工 ID：\n${targets.map(e=>`${e.name}: ${e.id}`).join('\n')}`);if(!targetId)return;if(!window.confirm('转交将在一个事务内解除旧员工并绑定新员工，确认继续？'))return;await api('binding-transfers',{method:'POST',headers:{'X-CSRF-Token':csrf},body:JSON.stringify({source_employee_id:source.id,target_employee_id:targetId})});await refresh()}
  const changeStatus=async(employee:Employee,status:string)=>{if(status!=='active'&&employee.binding&&!window.confirm('停用或离职会立即阻止新投递。是否继续？之后可在当前用户管理页解除并释放 Bot。'))return;await api(`employees/${employee.id}`,{method:'PATCH',headers:{'X-CSRF-Token':csrf},body:JSON.stringify({status})});await refresh()}
  const testSend=async(employee:Employee)=>{if(!employee.binding?.manual_test?.allowed)return;if(!window.confirm(`向 ${employee.name} 发送固定用途测试通知？\n目标 Bot：${employee.binding.account_id_masked}（${employee.binding.health_status}）\n提交后只表示进入真实投递流程，不代表员工已收到。`))return;setTestSending(employee.id);try{const result=await api(`employees/${employee.id}/test-notification`,{method:'POST',headers:{'X-CSRF-Token':csrf}}) as NoticeSummary;setTestResults(current=>({...current,[employee.id]:result}));await refresh();setTestResults(current=>{const next={...current};delete next[employee.id];return next})}finally{setTestSending('')}}
  const liveSession=(employee:Employee)=>Boolean(employee.binding_session&&['pending','scanned','confirming'].includes(employee.binding_session.status))
  return <Panel title="用户管理" action={<button className="primary small" onClick={()=>setOpen(!open)}>新增用户</button>}>{open&&<form className="inline-form" onSubmit={create}>{Object.keys(form).map(k=><input required={k==='name'} key={k} placeholder={{name:'用户姓名',department:'部门',content_vertical:'内容垂直领域',account_name:'账号名称'}[k]} value={form[k as keyof typeof form]} onChange={e=>setForm({...form,[k]:e.target.value})}/>)}<button className="primary">保存并绑定微信</button></form>}{rows.some(e=>e.binding&&!e.binding.delivery_ready)&&<p className="alert">待互动用户：请在微信里找到并打开该用户的独立微信 Bot 会话，直接回复“帮助”。不要发给扫码人的普通微信账号、文件传输助手或群聊。</p>}<table><thead><tr><th>公司</th><th>用户</th><th>部门</th><th>垂直领域</th><th>账号</th><th>账号状态</th><th>微信绑定</th><th>Bot 标识</th><th>最近健康</th><th>操作</th></tr></thead><tbody>{rows.map(e=>{const result=testResults[e.id]||e.binding?.manual_test?.latest_delivery;return <tr key={e.id}><td>{e.company_id}</td><td><b>{e.name}</b></td><td>{e.department||'—'}</td><td>{e.content_vertical||'—'}</td><td>{e.account_name||'—'}</td><td><select value={e.status} onChange={event=>void changeStatus(e,event.target.value)}><option value="active">启用</option><option value="disabled">停用</option><option value="departed">离职</option></select></td><td><Badge value={e.binding?(e.binding.delivery_ready?'bound':'waiting_interaction'):e.binding_session?.status||'unbound'}/>{e.binding?.welcome_delivery&&<small className="cell-detail">欢迎通知：{deliveryStatusText(e.binding.welcome_delivery.status)}</small>}</td><td>{e.binding?.account_id_masked||'未绑定'}</td><td>{e.binding?.health_status||'—'} {formatTime(e.binding?.last_health_at)}</td><td><div className="row-actions">{!e.binding&&!liveSession(e)&&<button className="small ghost" onClick={()=>void generate(e)}>生成/刷新二维码</button>}{liveSession(e)&&<button className="small ghost" onClick={()=>openBinding(e.binding_session!)}>查看二维码</button>}{e.binding&&<><button className="small ghost" disabled={!e.binding.manual_test?.allowed||testSending===e.id} title={e.binding.manual_test?.reason||`向 ${e.name} 的健康 Bot 发送固定测试通知`} onClick={()=>void testSend(e)}>{testSending===e.id?'发送中…':'测试发送'}</button><button className="small ghost danger" onClick={()=>void unbind(e)}>解除绑定</button><button className="small ghost" onClick={()=>void transfer(e)}>转交</button></>}{!e.binding&&<button className="small ghost" disabled title="员工尚未绑定微信 Bot">测试发送</button>}</div>{e.binding?.manual_test?.reason&&<small className="cell-detail">{e.binding.manual_test.reason}</small>}{result&&<small className="cell-detail">测试通知：{deliveryStatusText(result.status)}{result.failure_message?` · ${result.failure_message}`:''}</small>}</td></tr>})}</tbody></table></Panel>
}

function BindingModal({initial,csrf,onClose,onChanged}:{initial:BindingSession;csrf:string;onClose:()=>void;onChanged:()=>Promise<void>}) {
  const [session,setSession]=useState(initial)
  const [remaining,setRemaining]=useState(0)
  const [busy,setBusy]=useState(false)
  const live=['pending','scanned','confirming'].includes(session.status)
  useEffect(()=>{const tick=()=>setRemaining(Math.max(0,Math.ceil((new Date(session.expires_at).getTime()-Date.now())/1000)));tick();const timer=window.setInterval(tick,1000);return()=>window.clearInterval(timer)},[session.expires_at])
  useEffect(()=>{if(!live)return;const poll=async()=>{try{const next=await api(`binding-sessions/${session.id}/poll`,{method:'POST',headers:{'X-CSRF-Token':csrf}});setSession(next);if(next.status==='bound')await onChanged()}catch{/* 状态错误显示在下一轮或手动刷新 */}};const timer=window.setInterval(()=>void poll(),2000);return()=>window.clearInterval(timer)},[csrf,live,onChanged,session.id])
  const cancel=async()=>{setBusy(true);try{const next=await api(`binding-sessions/${session.id}/cancel`,{method:'POST',headers:{'X-CSRF-Token':csrf}});setSession(next);await onChanged()}finally{setBusy(false)}}
  const refreshQr=async()=>{setBusy(true);try{const next=await api(`employees/${session.employee_id}/binding-sessions`,{method:'POST',headers:{'X-CSRF-Token':csrf}});setSession(next);await onChanged()}finally{setBusy(false)}}
  return <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="用户微信 Bot 绑定"><section className="binding-modal"><button className="modal-close" onClick={onClose} aria-label="关闭"><X/></button><p className="eyebrow">iLink 独立 Bot 绑定</p><h3>请用户本人使用个人微信扫码</h3><div className="binding-progress"><Badge value={session.status}/><span>{statusText(session.status)}</span></div>{live&&session.qr_image_url&&<img className="qr-image" src={session.qr_image_url} alt="微信 Bot 绑定二维码"/>}<p className="countdown">二维码剩余有效时间：{Math.floor(remaining/60)}:{String(remaining%60).padStart(2,'0')}</p><p className="muted">扫码后请在微信中确认。二维码只编码短时登录票据，不包含用户 ID、手机号或 Bot 凭据。</p>{session.status==='bound'&&<p className="alert">Bot 身份已创建。请打开该独立 Bot 会话并直接回复“帮助”；不要发给扫码账号自身、文件传输助手或群聊。首次互动前的通知会排队，激活后自动补发。</p>}{session.failure_code&&<p className="error">状态码：{session.failure_code}</p>}<div className="modal-actions">{live&&<button disabled={busy} className="ghost danger" onClick={()=>void cancel()}>取消等待绑定</button>}{['expired','failed','cancelled'].includes(session.status)&&<button disabled={busy} className="primary" onClick={()=>void refreshQr()}>刷新二维码</button>}<button className="ghost" onClick={onClose}>{session.status==='bound'?'我已了解':'稍后处理'}</button></div></section></div>
}

function statusText(status:string){return ({pending:'等待扫码',scanned:'已扫码',confirming:'已扫码，等待微信确认',bound:'绑定成功',expired:'二维码已过期',cancelled:'已取消',failed:'失败',revoked:'已解除',sent:'已发送',confirmed:'已确认',waiting_interaction:'等待首次互动',retrying:'重试中'} as Record<string,string>)[status]||status}
function deliveryStatusText(status:string){return ({pending:'已排队',sending:'发送中',sent:'已发送',confirmed:'员工已确认',failed:'发送失败',waiting_interaction:'等待首次互动',retrying:'重试中',cancelled:'已取消'} as Record<string,string>)[status]||status}
function formatTime(value?:string){return value?new Date(value).toLocaleString():'—'}
function DeliveryTable({rows}:{rows:Delivery[]}) { return <table><thead><tr><th>通知</th><th>状态</th><th>重试</th><th>失败原因</th><th>时间</th></tr></thead><tbody>{rows.map(d=><tr key={d.id}><td><b>{d.title||'无标题'}</b><small className="cell-detail">{d.body||d.idempotency_key}</small></td><td><Badge value={d.status}/></td><td>{d.retry_count}</td><td>{d.failure_message||'—'}{d.failure_code&&<small className="cell-detail">{d.failure_code}</small>}</td><td>{formatTime(d.created_at)}</td></tr>)}</tbody></table> }
function Panel({title,action,children}:{title:string;action?:React.ReactNode;children:React.ReactNode}){return <section className="panel"><div className="panel-head"><h3>{title}</h3>{action}</div>{children}</section>}
function Stat({label,value}:{label:string;value:number}){return <div className="stat"><small>{label}</small><strong>{value}</strong></div>}
function Badge({value}:{value:string}){const labels:Record<string,string>={active:'启用',departed:'离职',disabled:'禁用',bound:'已绑定',unbound:'未绑定',pending:'等待扫码',scanned:'已扫码',confirming:'确认中',expired:'已过期',revoked:'已解除',sent:'已发送',confirmed:'已确认',failed:'失败',waiting_interaction:'待互动',retrying:'重试中',cancelled:'已取消'};return <span className={`badge ${value}`}>{labels[value]||value}</span>}
