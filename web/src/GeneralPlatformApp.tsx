import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Activity, BellRing, Bot, Building2, Check, Copy, KeyRound, LayoutDashboard, LogOut, Network, Plus, Settings, ShieldCheck, Users, X } from 'lucide-react'
import './platform.css'

type Company={company_id:string;company_slug:string;name:string;enabled:boolean;api_base_url?:string;api_address_scope?:string;api_address_warning?:string}

type UserContact={employee_id:string;name:string;masked_phone?:string;phone?:string;status:string;binding?:{binding_id?:string;status:string;health_status?:string;bot_masked?:string;manual_test?:{allowed:boolean}};binding_session?:BindSession}
type UserObject={user_object_code:string;account_name:string;enabled:boolean;manageable?:boolean;bound_count:number;pending_count:number;unhealthy_count:number;last_test_at?:string;all_available?:boolean;contacts?:UserContact[]}
type Batch={id:string;status:string;total:number;sent:number;failed:number;skipped:number;title:string;created_at:string;deliveries:Array<{delivery_id:string;bot_masked:string;status:string;failure_message?:string}>}
type Client={id:string;name:string;token_prefix:string;permissions:string[];allowed_target_codes:string[];enabled:boolean;last_used_at?:string}
type IntegrationGuide={api_base_url:string;api_address_scope:string;api_address_warning:string;company_id:string;company_slug:string;company_name:string;client_id:string;client_name:string;permissions:string[];all_user_objects:boolean;allowed_user_objects:Array<{user_object_code:string;account_name:string;enabled:boolean}>;delivery_mode:string;guide_markdown:string;curl_check:string}
type IssuedCredential=Client&{token:string;integration:IntegrationGuide}
type ClientForm={name:string;permission_preset:'notification'|'query'|'custom';permissions:string[];object_scope:'all'|'selected';allowed_target_codes:string[]}
type BindSession={id:string;employee_id:string;status:string;qr_image_url?:string;failure_code?:string}
type Act=(work:()=>Promise<void>)=>void

const nav=[['overview','总览',LayoutDashboard],['companies','公司管理',Building2],['targets','用户对象',Users],['batches','通知任务',BellRing],['api','应用接入',KeyRound],['settings','系统设置',Settings]] as const
const labels:Record<string,string>={active:'启用',disabled:'停用',healthy:'健康',degraded:'异常',unknown:'未知',revoked:'已撤销',pending:'待处理',completed:'全部成功',partial:'部分成功',failed:'失败',sent:'已发送',simulated:'仅模拟，未发送',confirmed:'已确认',waiting_interaction:'等待首次互动',cancelled:'已取消',bound:'绑定成功',scanned:'已扫码',confirming:'确认中',expired:'已过期'}
let authGeneration=0
class StaleAuthResponseError extends Error{}
const isStaleAuthResponse=(error:unknown)=>error instanceof StaleAuthResponseError

async function api(path:string,options:RequestInit={},allowStaleAuthResponse=false){const requestGeneration=authGeneration;const r=await fetch(`api/v1/${path}`,{credentials:'same-origin',...options,headers:{'Content-Type':'application/json',...(options.headers||{})}});const data=await r.json().catch(()=>({}));if(requestGeneration!==authGeneration&&!allowStaleAuthResponse)throw new StaleAuthResponseError();if(r.status===401&&requestGeneration===authGeneration)window.dispatchEvent(new Event('evnc:unauthorized'));if(!r.ok)throw new Error(data.detail||`请求失败 (${r.status})`);return data}
function write(csrf:string,method:string,body?:unknown):RequestInit{return{method,headers:{'X-CSRF-Token':csrf},body:body===undefined?undefined:JSON.stringify(body)}}
async function copyText(value:string){if(navigator.clipboard?.writeText){await navigator.clipboard.writeText(value);return}const field=document.createElement('textarea');field.value=value;field.setAttribute('readonly','');field.style.position='fixed';field.style.opacity='0';document.body.appendChild(field);field.select();const copied=document.execCommand?.('copy');field.remove();if(!copied)throw new Error('浏览器未允许复制，请使用 HTTPS 或手动复制')}

export function GeneralPlatformApp(){
 const[csrf,setCsrf]=useState('');const[role,setRole]=useState('');const[section,setSection]=useState('overview');const[loading,setLoading]=useState(true);const[pending,setPending]=useState(false)
 const[companies,setCompanies]=useState<Company[]>([]);const[company,setCompany]=useState('');const[userObjects,setUserObjects]=useState<UserObject[]>([]);const[batches,setBatches]=useState<Batch[]>([]);const[clients,setClients]=useState<Client[]>([])
 const[error,setError]=useState('');const[notice,setNotice]=useState('');const[login,setLogin]=useState({username:'',password:''});const[loginBusy,setLoginBusy]=useState(false);const[issuedCredential,setIssuedCredential]=useState<IssuedCredential>();const[oneTimeTokenPending,setOneTimeTokenPending]=useState(false)
 const refreshGeneration=useRef(0);const refreshFailureContext=useRef('')
 const act:Act=work=>{setError('');setNotice('');void work().catch(e=>{if(!isStaleAuthResponse(e))setError((e as Error).message)})}
 useEffect(()=>{void api('auth/session').then(r=>{authGeneration++;setCsrf(r.csrf_token);setRole(r.role)}).catch(()=>{}).finally(()=>setLoading(false))},[])
 const clearTenantState=(clearToken=true)=>{refreshGeneration.current++;setCompany('');setCompanies([]);setUserObjects([]);setBatches([]);setClients([]);setNotice('');setError('');setSection('overview');setPending(false);if(clearToken){setIssuedCredential(undefined);setOneTimeTokenPending(false)}}
 useEffect(()=>{const unauthorized=()=>{authGeneration++;clearTenantState(false);setCsrf('');setRole('');setLogin({username:'',password:''});setLoading(false)};window.addEventListener('evnc:unauthorized',unauthorized);return()=>window.removeEventListener('evnc:unauthorized',unauthorized)},[])
 const refresh=useCallback(async()=>{if(!csrf)return;const generation=++refreshGeneration.current;setLoading(true);try{const cs=await api('companies') as Company[];if(generation!==refreshGeneration.current)return;const selected=cs.some(c=>c.company_id===company)?company:(cs[0]?.company_id||'');if(selected){const[objects,ns,as]=await Promise.all([api(`companies/${selected}/user-objects`),api(`notification-batches?company_id=${selected}`),api(`api-clients?company_id=${selected}`)]);if(generation!==refreshGeneration.current)return;setCompanies(cs);setCompany(selected);setUserObjects(objects);setBatches(ns);setClients(as)}else{setCompanies(cs);setCompany('');setUserObjects([]);setBatches([]);setClients([])}refreshFailureContext.current=''}finally{if(generation===refreshGeneration.current)setLoading(false)}},[company,csrf])
 useEffect(()=>{void refresh().catch(e=>{if(isStaleAuthResponse(e))return;const context=refreshFailureContext.current;refreshFailureContext.current='';setError(context?`${context}${(e as Error).message}。公司已创建，请勿重复提交`:(e as Error).message)})},[refresh])
 const switchCompany=(id:string,successNotice='')=>{refreshGeneration.current++;refreshFailureContext.current=successNotice?'公司已创建，但新公司数据刷新失败：':'';setLoading(true);setCompany(id);setUserObjects([]);setBatches([]);setClients([]);setNotice(successNotice);setError('')}
 const submitLogin=(e:React.FormEvent)=>{e.preventDefault();if(loginBusy)return;setLoginBusy(true);act(async()=>{try{const r=await api('auth/login',{method:'POST',body:JSON.stringify(login)});authGeneration++;setCsrf(r.csrf_token);setRole(r.role);setLogin({username:'',password:''})}finally{setLoginBusy(false)}})}
 const current=companies.find(c=>c.company_id===company);const stats=useMemo(()=>({targets:userObjects.filter(t=>t.enabled).length,bots:userObjects.reduce((n,t)=>n+(t.bound_count||0),0),healthy:userObjects.reduce((n,t)=>n+Math.max(0,(t.bound_count||0)-(t.unhealthy_count||0)),0),failed:batches.filter(b=>b.failed>0).length}),[userObjects,batches])
 if(loading&&!csrf)return <main className="login-shell"><section className="login-card"><div className="brand-mark"><Bot/></div><h1>个人微信 Bot 通知平台</h1><p>正在检查安全会话…</p></section></main>
 if(!csrf&&issuedCredential)return <main className="login-shell"><section className="login-card credential-login"><div className="brand-mark"><KeyRound/></div><h1>会话已失效</h1><p className="muted">为防止一次性 Token 在重新登录后暴露给另一身份，请先保存并确认关闭；在此之前不会显示登录表单。</p><CredentialPanel credential={issuedCredential} close={()=>setIssuedCredential(undefined)} sessionExpired/></section></main>
 if(!csrf&&oneTimeTokenPending)return <main className="login-shell"><section className="login-card"><div className="brand-mark"><KeyRound/></div><h1>会话已失效</h1><p className="muted" role="status">一次性 Token 请求仍在完成中。为防止唯一凭据丢失或暴露给另一身份，请等待结果；完成前不会显示登录表单。</p></section></main>
 if(!csrf)return <main className="login-shell"><section className="login-card"><div className="brand-mark"><Bot/></div><p className="eyebrow">Multi-company notification infrastructure</p><h1>个人微信 Bot 通知平台</h1><p className="muted">统一管理公司、用户对象及其内联微信 Bot 和公司级 API 授权。</p><form onSubmit={submitLogin}><label>用户名<input autoComplete="username" value={login.username} onChange={e=>setLogin({...login,username:e.target.value})}/></label><label>密码<input type="password" autoComplete="current-password" value={login.password} onChange={e=>setLogin({...login,password:e.target.value})}/></label>{error&&<p className="error" role="alert">{error}</p>}<button className="primary" type="submit" disabled={loginBusy}>{loginBusy?'登录中…':'安全登录'}</button></form><p className="developer-credit">由 <strong>猫王AI</strong> 开发与维护</p></section></main>
 const sessionGeneration=authGeneration
 const setSessionPending=(value:boolean)=>{if(sessionGeneration===authGeneration)setPending(value)}
 const props={csrf,role,company,current,companies,userObjects,batches,clients,stats,refresh,act,notify:setNotice,selectCompany:switchCompany,pending,setPending:setSessionPending,setIssuedCredential,setOneTimeTokenPending}
 const navigate=(id:string)=>{setSection(id);setError('');setNotice('')}
 const transitionLocked=pending||loading||!!issuedCredential
 return <div className="app-shell"><aside><div className="brand"><div className="brand-mark"><Bot size={22}/></div><div><strong>微信 Bot 通知平台</strong><small>Notification Platform</small></div></div><nav>{nav.map(([id,label,Icon])=><button type="button" aria-label={label} key={id} disabled={transitionLocked} className={section===id?'active':''} onClick={()=>navigate(id)}><Icon size={18}/><span>{label}</span></button>)}</nav><div className="sidebar-credit"><span>DEVELOPED BY</span><strong>猫王AI</strong></div><button type="button" className="logout" aria-label="退出登录" disabled={transitionLocked} onClick={()=>{const logoutGeneration=authGeneration;setPending(true);act(async()=>{try{await api('auth/logout',write(csrf,'POST'));authGeneration++;clearTenantState();setCsrf('');setRole('');setLogin({username:'',password:''})}finally{if(logoutGeneration===authGeneration)setPending(false)}})}}><LogOut size={17}/><span>退出登录</span></button></aside><main className="workspace"><header><div><p className="eyebrow">公司级授权 · 精确投递</p><h2>{nav.find(s=>s[0]===section)?.[1]}</h2></div><div className="header-actions"><select aria-label="当前公司" value={company} onChange={e=>switchCompany(e.target.value)} disabled={transitionLocked}>{companies.map(c=><option key={c.company_id} value={c.company_id}>{c.name}{c.enabled?'':'（已停用）'}</option>)}</select><button type="button" className="ghost" onClick={()=>act(refresh)} disabled={loading||pending}><Activity size={16}/>{loading?'加载中':'刷新'}</button></div></header>{issuedCredential&&<CredentialPanel credential={issuedCredential} close={()=>setIssuedCredential(undefined)}/>} {error&&<div className="alert error" role="alert">{error}</div>}{notice&&<div className="alert success" role="status">{notice}</div>}{(loading||pending)&&<div className="loading-note" role="status">{pending?'正在安全处理操作，完成前已锁定公司切换、导航和退出。':'正在加载当前公司数据，期间已禁用公司切换和重复刷新。'}</div>}<Content key={`${company}:${section}`} section={section}{...props}/></main></div>
}

type Props={csrf:string;role:string;company:string;current?:Company;companies:Company[];userObjects:UserObject[];batches:Batch[];clients:Client[];stats:Record<string,number>;refresh:()=>Promise<void>;act:Act;notify:(s:string)=>void;selectCompany:(id:string,successNotice?:string)=>void;pending:boolean;setPending:(value:boolean)=>void;setIssuedCredential:(value:IssuedCredential|undefined)=>void;setOneTimeTokenPending:(value:boolean)=>void}
function CredentialPanel({credential,close,sessionExpired=false}:{credential:IssuedCredential;close:()=>void;sessionExpired?:boolean}){
 const[copied,setCopied]=useState('');const[copyError,setCopyError]=useState('')
 const copy=async(value:string,label:string)=>{setCopyError('');try{await copyText(value);setCopied(label)}catch(error){setCopied('');setCopyError((error as Error).message)}}
 const integration=credential.integration
 return <section className="token-once credential-panel" role="status" aria-label="一次性应用接入凭据">
  {!sessionExpired&&<button type="button" className="token-dismiss" onClick={close} aria-label="关闭一次性 Token"><X size={18}/></button>}
  <div className="credential-heading"><ShieldCheck size={22}/><div><b>应用接入已创建，Token 仅显示这一次</b><p>先把 Token 保存到调用应用的秘密环境，再复制不含密钥的 AI 接入说明。</p></div></div>
  <div className="credential-meta"><div><span>API 调用地址</span><code>{integration.api_base_url}</code></div><div><span>公司标识</span><code>{integration.company_slug}</code></div><div><span>投递模式</span><strong>{integration.delivery_mode==='weixin'?'微信投递模式':'非正式模式'}</strong></div></div>
  {integration.api_address_warning&&<p className="connection-warning"><Network size={16}/>{integration.api_address_warning}</p>}
  <label className="credential-secret"><span>一次性 Token</span><code>{credential.token}</code></label>
  <div className="credential-actions">
   <button type="button" className="ghost" onClick={()=>void copy(credential.token,'Token 已复制')}><Copy size={16}/>复制 Token</button>
   <button type="button" className="primary" onClick={()=>void copy(integration.guide_markdown,'AI 接入说明已复制')}><Copy size={16}/>一键复制 AI 接入说明</button>
   <button type="button" className="ghost" onClick={()=>void copy(integration.curl_check,'自检命令已复制')}><Copy size={16}/>复制自检命令</button>
  </div>
  <p className="secret-guidance">AI 接入说明不包含真实 Token；请让 AI 只读取环境变量 <code>EMPLOYEE_VIDEO_NOTIFICATION_API_TOKEN</code>。</p>
  {copied&&<p className="copy-result" aria-live="polite"><Check size={15}/>{copied}</p>}{copyError&&<p className="form-error" role="alert">{copyError}</p>}
  <button type="button" className="credential-acknowledge" onClick={close}>{sessionExpired?'确认已保存并返回登录':'我已安全保存 Token'}</button>
 </section>
}
function Content(p:Props&{section:string}){if(p.section==='overview')return <><div className="stat-grid"><Stat label="启用用户对象" value={p.stats.targets}/><Stat label="已绑定微信 Bot" value={p.stats.bots}/><Stat label="健康可发送" value={p.stats.healthy}/><Stat label="异常批次" value={p.stats.failed}/></div>{p.current&&!p.current.enabled&&<div className="alert error">当前公司已停用，预览、测试和正式发送均被后端阻止。</div>}<Panel title="近期通知任务"><BatchList rows={p.batches.slice(0,6)}/></Panel></>;if(p.section==='companies')return <Companies {...p}/>;if(p.section==='targets')return <UserObjects {...p}/>;if(p.section==='batches')return <Panel title="通知任务与逐 Bot 结果"><BatchList rows={p.batches}/></Panel>;if(p.section==='api')return <Clients {...p}/>;return <Panel title="系统设置"><div className="empty"><Settings/><b>统一服务，统一部署</b><p>完整凭据绝不回显；Token 仅创建或轮换时显示一次。</p></div></Panel>}

function Companies({csrf,role,companies,refresh,selectCompany,notify,setPending}:Props){
 const[mode,setMode]=useState<'create'|'edit'|''>('');const[editing,setEditing]=useState<Company>();const[form,setForm]=useState({company_slug:'',name:''});const[busy,setBusy]=useState(false);const[actionBusy,setActionBusy]=useState('');const[formError,setFormError]=useState('');const[actionError,setActionError]=useState('')
 const open=mode!==''
 const reset=()=>{setMode('');setEditing(undefined);setForm({company_slug:'',name:''});setFormError('')}
 const beginCreate=()=>{reset();setMode('create')}
 const beginEdit=(item:Company)=>{setMode('edit');setEditing(item);setForm({company_slug:item.company_slug,name:item.name});setFormError('')}
 const submit=async(e:React.FormEvent)=>{e.preventDefault();if(busy)return;setBusy(true);setPending(true);setFormError('');try{if(editing){await api(`companies/${editing.company_id}`,write(csrf,'PATCH',{name:form.name}));reset();notify('公司修改已保存。');try{await refresh()}catch{setActionError('公司修改已保存，但列表刷新失败，请手动刷新')}}else{const created=await api('companies',write(csrf,'POST',form)) as Company;reset();selectCompany(created.company_id,'公司创建成功，正在加载新公司数据。')}}catch(err){setFormError((err as Error).message)}finally{setBusy(false);setPending(false)}}
 const toggle=async(item:Company)=>{if(item.enabled&&!confirm(`确认停用 ${item.name}？停用后该公司的预览、测试和发送都会立即被阻止。`))return;setActionBusy(item.company_id);setPending(true);setActionError('');try{await api(`companies/${item.company_id}`,write(csrf,'PATCH',{enabled:!item.enabled}));notify(`公司已${item.enabled?'停用':'启用'}。`);try{await refresh()}catch{setActionError('状态修改已保存，但列表刷新失败，请手动刷新')}}catch(err){setActionError((err as Error).message)}finally{setActionBusy('');setPending(false)}}
 return <Panel title="公司管理" action={role==='super_admin'?<button type="button" className="primary small" onClick={beginCreate} disabled={open||busy}><Plus size={15}/>新增公司</button>:undefined}>
  {actionError&&<p className="form-error" role="alert">{actionError}。请刷新公司列表后重试。</p>}{open&&<form className="inline-form temporary-form" aria-label={editing?'编辑公司':'新增公司'} onSubmit={submit} onKeyDown={e=>{if(e.key==='Escape'&&!busy){e.preventDefault();reset()}}}>
   <label>公司标识<input required disabled={!!editing||busy} pattern="[a-z0-9][a-z0-9-]{1,62}[a-z0-9]" placeholder="稳定 company_slug" value={form.company_slug} onChange={e=>setForm({...form,company_slug:e.target.value})}/></label>
   <label>公司名称<input required disabled={busy} placeholder="公司显示名称" value={form.name} onChange={e=>setForm({...form,name:e.target.value})}/></label>
   {formError&&<p className="form-error" role="alert">{formError}。请检查公司标识和名称后重试，或取消本次操作。</p>}
   <div className="form-actions"><button className="primary" type="submit" disabled={busy}>{busy?'保存中…':editing?'保存修改':'创建公司'}</button><button className="ghost" type="button" onClick={reset} disabled={busy}>取消</button></div>
  </form>}
  <div className="card-list">{companies.map(c=><article className="item-card" key={c.company_id}><div><b>{c.name}</b><code>{c.company_slug}</code></div><Badge value={c.enabled?'active':'disabled'}/><div className="row-actions"><button type="button" className="ghost small" onClick={()=>beginEdit(c)} disabled={open||!!actionBusy}>编辑</button><button type="button" className="ghost small" disabled={!!actionBusy} onClick={()=>void toggle(c)}>{actionBusy===c.company_id?'处理中…':c.enabled?'停用':'启用'}</button></div></article>)}</div>
 </Panel>
}

function UserObjects({csrf,company,userObjects,refresh,notify,setPending}:Props){
 const[createOpen,setCreateOpen]=useState(false)
 const[name,setName]=useState('')
 const[expanded,setExpanded]=useState('')
 const[details,setDetails]=useState<Record<string,UserObject>>({})
 const[editName,setEditName]=useState('')
 const[contactMode,setContactMode]=useState<{code:string;contact?:UserContact}>()
 const[contactForm,setContactForm]=useState({name:'',phone:''})
 const[session,setSession]=useState<BindSession>()
 const[busy,setBusy]=useState('')
 const[error,setError]=useState('')
 const returnFocus=useRef<HTMLElement|null>(null)
 const base=`companies/${company}/user-objects`
 const refreshAfter=async(message:string)=>{notify(message);try{await refresh()}catch{setError(`${message.replace(/。$/,'')}，但列表刷新失败，请手动刷新`)}}
 const invalidate=(code:string)=>setDetails(old=>{const next={...old};delete next[code];return next})
 const create=async(e:React.FormEvent)=>{e.preventDefault();if(busy)return;setBusy('create');setPending(true);setError('');try{await api(base,write(csrf,'POST',{account_name:name}));setCreateOpen(false);setName('');await refreshAfter('用户对象创建成功。')}catch(err){setError((err as Error).message)}finally{setBusy('');setPending(false)}}
 const expand=async(item:UserObject)=>{const code=item.user_object_code;if(expanded===code){setExpanded('');setContactMode(undefined);return}setExpanded(code);setContactMode(undefined);if(details[code])return;setBusy(`detail:${code}`);setError('');try{const detail=await api(`${base}/${code}`) as UserObject;setDetails(old=>({...old,[code]:detail}))}catch(err){setError((err as Error).message)}finally{setBusy('')}}
 const mutate=async(key:string,path:string,method:string,message:string,question?:string,body?:unknown)=>{if(busy||question&&!confirm(question))return;setBusy(key);setPending(true);setError('');try{await api(path,write(csrf,method,body));invalidate(expanded);setExpanded('');await refreshAfter(message)}catch(err){setError((err as Error).message)}finally{setBusy('');setPending(false)}}
 const saveObject=async(e:React.FormEvent,item:UserObject)=>{e.preventDefault();await mutate(`edit:${item.user_object_code}`,`${base}/${item.user_object_code}`,'PATCH','用户对象修改已保存。',undefined,{account_name:editName});setEditName('')}
 const beginContact=(code:string,contact?:UserContact)=>{setContactMode({code,contact});setContactForm({name:contact?.name||'',phone:contact?.phone||''});setError('')}
 const saveContact=async(e:React.FormEvent)=>{e.preventDefault();if(!contactMode||busy)return;const{code,contact}=contactMode;setBusy(`contact:${code}`);setPending(true);setError('');try{const path=contact?`${base}/${code}/contacts/${contact.employee_id}`:`${base}/${code}/contacts`;await api(path,write(csrf,contact?'PATCH':'POST',{name:contactForm.name,phone:contactForm.phone}));setContactMode(undefined);setContactForm({name:'',phone:''});invalidate(code);setExpanded('');await refreshAfter(contact?'联系人修改已保存。':'联系人添加成功。')}catch(err){setError((err as Error).message)}finally{setBusy('');setPending(false)}}
 const openBinding=async(code:string,contact:UserContact,trigger:HTMLElement)=>{setBusy(`bind:${contact.employee_id}`);setPending(true);setError('');returnFocus.current=trigger;try{const live=contact.binding_session&&['pending','scanned','confirming'].includes(contact.binding_session.status);setSession(live?contact.binding_session:await api(`${base}/${code}/contacts/${contact.employee_id}/binding-sessions`,write(csrf,'POST')))}catch(err){setError((err as Error).message)}finally{setBusy('');setPending(false)}}
 const testContact=async(contact:UserContact)=>{if(busy||!confirm(`确认向 ${contact.name} 发送安全测试通知？`))return;setBusy(`test:${contact.employee_id}`);setPending(true);setError('');try{const result=await api(`employees/${contact.employee_id}/test-notification`,write(csrf,'POST'));notify(result.status==='simulated'?'安全测试仅在隔离环境模拟，未发送微信。':'安全测试已由微信通道发送；该状态不代表联系人已确认。');invalidate(expanded);setExpanded('');try{await refresh()}catch{setError('测试结果已记录，但列表刷新失败，请手动刷新')}}catch(err){setError((err as Error).message)}finally{setBusy('');setPending(false)}}
 const closeModal=()=>{setSession(undefined);queueMicrotask(()=>returnFocus.current?.focus())}
 return <>
  <Panel title="用户对象" action={<button type="button" className="primary small" disabled={createOpen||!!busy} onClick={()=>setCreateOpen(true)}><Plus size={15}/>创建用户对象</button>}>
   {error&&<p className="form-error" role="alert">{error}。已保留未完成输入，请检查状态后重试。</p>}
   {createOpen&&<form className="inline-form temporary-form" aria-label="新增用户对象" onSubmit={create} onKeyDown={e=>{if(e.key==='Escape'&&!busy){setCreateOpen(false);setName('')}}}>
    <label>账号名称<input autoFocus required disabled={!!busy} value={name} onChange={e=>setName(e.target.value)}/></label>
    <div className="form-actions"><button className="primary" type="submit" disabled={!!busy}>{busy==='create'?'创建中…':'创建'}</button><button className="ghost" type="button" disabled={!!busy} onClick={()=>{setCreateOpen(false);setName('')}}>取消</button></div>
   </form>}
   <div className="card-list user-object-list">{userObjects.length?userObjects.map(item=>{
    const code=item.user_object_code,detail=details[code],contacts=detail?.contacts||[],open=expanded===code
    return <article className="user-object-card" key={code}>
     <div className="user-object-summary">
      <div><b>{item.account_name}</b><small>最近测试 {time(item.last_test_at)}</small></div>
      <div className="object-counts"><span>已绑定 {item.bound_count||0}</span><span>待绑定 {item.pending_count||0}</span><span className={item.unhealthy_count?'danger':''}>异常 {item.unhealthy_count||0}</span></div>
      <Badge value={item.enabled?'active':'disabled'}/>
      <button type="button" className="ghost small" disabled={!!busy} aria-expanded={open} aria-label={`${open?'收起':'展开'}${item.account_name}详情`} onClick={()=>void expand(item)}>{busy===`detail:${code}`?'加载中…':open?'收起详情':'查看详情'}</button>
     </div>
     {open&&<section className="user-object-detail" aria-label={`${item.account_name}详情`}>
      {item.manageable!==false&&<div className="row-actions object-actions">
       <button type="button" className="ghost small" disabled={!!busy} onClick={()=>setEditName(item.account_name)}>编辑</button>
       <button type="button" className="ghost small" disabled={!!busy} onClick={()=>beginContact(code)}>添加联系人</button>
       <button type="button" className="ghost small" disabled={!!busy||item.all_available} onClick={()=>void mutate(`bindall:${code}`,`${base}/${code}/bind-all`,'POST','已绑定全部可用 Bot。')}>绑定全部可用 Bot</button>
       <button type="button" className="ghost small" disabled={!!busy} onClick={()=>void mutate(`toggle:${code}`,`${base}/${code}`,'PATCH',`用户对象已${item.enabled?'停用':'启用'}。`,item.enabled?`确认停用“${item.account_name}”？`:undefined,{enabled:!item.enabled,confirm:item.enabled})}>{item.enabled?'停用':'启用'}</button>
       <button type="button" className="ghost small danger" disabled={!!busy||item.all_available} onClick={()=>void mutate(`delete:${code}`,`${base}/${code}`,'DELETE','用户对象已删除。',`确认删除“${item.account_name}”？`,{confirm:true})}>删除</button>
      </div>}
      {item.all_available&&<p className="muted">该兼容对象会在每次通知时动态使用当时全部有效 Bot，收件范围不会被静默固定。</p>}
      {editName&&<form className="inline-form temporary-form" aria-label="编辑用户对象" onSubmit={e=>void saveObject(e,item)}><label>账号名称<input required disabled={!!busy} value={editName} onChange={e=>setEditName(e.target.value)}/></label><div className="form-actions"><button className="primary" type="submit">保存修改</button><button className="ghost" type="button" onClick={()=>setEditName('')}>取消</button></div></form>}
      {contactMode?.code===code&&<form className="inline-form temporary-form" aria-label={contactMode.contact?'编辑联系人':'添加联系人'} onSubmit={saveContact} onKeyDown={e=>{if(e.key==='Escape'&&!busy)setContactMode(undefined)}}>
       <label>姓名<input required disabled={!!busy} value={contactForm.name} onChange={e=>setContactForm({...contactForm,name:e.target.value})}/></label>
       <label>电话<input required disabled={!!busy} inputMode="tel" value={contactForm.phone} onChange={e=>setContactForm({...contactForm,phone:e.target.value})}/></label>
       <div className="form-actions"><button className="primary" type="submit">{contactMode.contact?'保存修改':'保存联系人'}</button><button className="ghost" type="button" onClick={()=>setContactMode(undefined)}>取消</button></div>
      </form>}
      <div className="contact-list">{contacts.length?contacts.map(contact=>{
       const binding=contact.binding,live=contact.binding_session&&['pending','scanned','confirming'].includes(contact.binding_session.status)
       return <article className="contact-card" key={contact.employee_id}>
        <div><b>{contact.name}</b><span>{contact.masked_phone||'未填写电话'}</span><small>绑定：{labels[binding?.status||contact.binding_session?.status||'pending']} · 健康：{labels[binding?.health_status||'unknown']}</small></div>
        <div className="contact-status"><Badge value={binding?.status||contact.binding_session?.status||'pending'}/><Badge value={binding?.health_status||'unknown'}/></div>
        {item.manageable!==false&&<div className="row-actions">
         <button type="button" className="ghost small" disabled={!!busy} onClick={()=>beginContact(code,contact)}>编辑</button>
         {!binding&&<button type="button" className="ghost small" disabled={!!busy} onClick={e=>void openBinding(code,contact,e.currentTarget)}>{live?'查看二维码':'生成二维码'}</button>}
         {binding&&<><button type="button" className="ghost small" disabled={!!busy||binding.manual_test?.allowed===false} onClick={()=>void testContact(contact)}>逐 Bot 安全测试</button><button type="button" className="ghost small danger" disabled={!!busy} onClick={()=>void mutate(`unbind:${contact.employee_id}`,`${base}/${code}/contacts/${contact.employee_id}/unbind`,'POST','Bot 已解绑，历史记录已保留。',`确认解绑 ${contact.name} 的微信 Bot？`,{confirm:true})}>解绑</button></>}
         {!item.all_available&&<button type="button" className="ghost small" disabled={!!busy} onClick={()=>void mutate(`remove:${contact.employee_id}`,`${base}/${code}/contacts/${contact.employee_id}`,'DELETE','联系人已从当前对象移除。',`确认将 ${contact.name} 从当前对象移除？`,{confirm:true})}>从当前对象移除</button>}
         {!item.all_available&&<button type="button" className="ghost small danger" disabled={!!busy||contact.status==='disabled'} onClick={()=>void mutate(`deactivate-contact:${contact.employee_id}`,`${base}/${code}/contacts/${contact.employee_id}/deactivate`,'POST','联系人已停用，历史记录已保留。',`确认停用联系人 ${contact.name}？`,{confirm:true})}>停用联系人</button>}
        </div>}
       </article>
      }):detail&&<Empty text="当前对象暂无联系人；可在上方直接添加。"/>}</div>
     </section>}
    </article>
   }):<Empty text="当前公司暂无用户对象；请先创建账号。"/>}</div>
  </Panel>
  {session&&<BindingModal initial={session} csrf={csrf} close={closeModal} refresh={refresh} setPending={setPending} retryPath={`${base}/${expanded}/contacts/${session.employee_id}/binding-sessions`}/>}
 </>
}

function Clients({csrf,company,current,clients,userObjects,refresh,notify,setPending,setIssuedCredential,setOneTimeTokenPending}:Props){
 const permissionOrder=['query','send','status'];const permissionLabels:Record<string,string>={query:'读取对象与预览',send:'发送通知',status:'查询结果'}
 const freshForm=():ClientForm=>{const first=userObjects.find(item=>item.enabled)?.user_object_code;return{name:'',permission_preset:'notification',permissions:[...permissionOrder],object_scope:first?'selected':'all',allowed_target_codes:first?[first]:[]}}
 const[open,setOpen]=useState(false);const[editing,setEditing]=useState<Client>();const[form,setForm]=useState<ClientForm>(freshForm);const[busy,setBusy]=useState('');const[error,setError]=useState('')
 const toggle=(values:string[],value:string)=>values.includes(value)?values.filter(x=>x!==value):[...values,value]
 const reset=()=>{setOpen(false);setEditing(undefined);setForm(freshForm());setError('')}
 const beginCreate=()=>{setEditing(undefined);setForm(freshForm());setError('');setOpen(true)}
 const inferPreset=(permissions:string[]):ClientForm['permission_preset']=>permissionOrder.every(x=>permissions.includes(x))&&permissions.length===3?'notification':permissions.length===1&&permissions[0]==='query'?'query':'custom'
 const beginEdit=(c:Client)=>{setEditing(c);setForm({name:c.name,permission_preset:inferPreset(c.permissions),permissions:[...c.permissions],object_scope:c.allowed_target_codes.length?'selected':'all',allowed_target_codes:[...c.allowed_target_codes]});setError('');setOpen(true)}
 const selectPermissionPreset=(preset:ClientForm['permission_preset'])=>setForm({...form,permission_preset:preset,permissions:preset==='notification'?[...permissionOrder]:preset==='query'?['query']:form.permissions})
 const submit=async(e:React.FormEvent)=>{e.preventDefault();if(busy)return;if(!form.permissions.length){setError('至少选择一项调用权限');return}if(form.object_scope==='selected'&&!form.allowed_target_codes.length){setError('请至少选择一个用户对象，或明确允许全部对象');return}const payload={name:form.name,permissions:form.permissions,allowed_target_codes:form.object_scope==='all'?[]:form.allowed_target_codes};const issuingToken=!editing;setBusy('save');setPending(true);if(issuingToken)setOneTimeTokenPending(true);setError('');try{if(editing){await api(`api-clients/${editing.id}`,write(csrf,'PATCH',payload));notify('应用接入配置已保存。')}else{const issued=await api('api-clients',write(csrf,'POST',{company_id:company,...payload}),true) as IssuedCredential;setIssuedCredential(issued);notify('应用接入已创建，请立即保存一次性 Token。')}reset();try{await refresh()}catch{setError('接入配置已保存，但列表刷新失败；请先保存一次性 Token，再手动刷新')}}catch(err){setError((err as Error).message)}finally{if(issuingToken)setOneTimeTokenPending(false);setBusy('');setPending(false)}}
 const copyGuide=async(c:Client)=>{setBusy(`guide:${c.id}`);setError('');try{const integration=await api(`api-clients/${c.id}/integration-guide`) as IntegrationGuide;await copyText(integration.guide_markdown);notify('AI 接入说明已复制，不包含真实 Token。')}catch(err){setError((err as Error).message)}finally{setBusy('')}}
 const rotate=async(c:Client)=>{if(!confirm(`确认轮换 ${c.name} 的 Token？旧 Token 会立即失效，且新 Token 只显示一次。`))return;setBusy(`rotate:${c.id}`);setPending(true);setOneTimeTokenPending(true);setError('');try{const issued=await api(`api-clients/${c.id}/rotate`,write(csrf,'POST'),true) as IssuedCredential;setIssuedCredential(issued);notify('Token 轮换成功，请立即保存新 Token。');try{await refresh()}catch{setError('Token 已轮换但列表刷新失败；请先保存新 Token，再手动刷新')}}catch(err){setError((err as Error).message)}finally{setOneTimeTokenPending(false);setBusy('');setPending(false)}}
 const remove=async(c:Client)=>{if(!confirm(`确认删除 ${c.name}？该应用和 Token 会被永久删除，且无法恢复。`))return;setBusy(`delete:${c.id}`);setPending(true);setError('');try{await api(`api-clients/${c.id}`,write(csrf,'DELETE',{confirm:true}));notify('应用接入已永久删除。');try{await refresh()}catch{setError('应用已删除，但列表刷新失败，请手动刷新')}}catch(err){setError((err as Error).message)}finally{setBusy('');setPending(false)}}
 const objectName=(code:string)=>userObjects.find(item=>item.user_object_code===code)?.account_name||code
 return <Panel title="外部应用接入" action={<button type="button" className="primary small" onClick={beginCreate} disabled={open||!!busy}><Plus size={15}/>接入新应用</button>}>
  <section className="connection-summary" aria-label="API 调用地址"><div className="connection-icon"><Network size={20}/></div><div><span>服务端 API 地址</span><code>{current?.api_base_url||'尚未配置'}</code><small>外部应用应从后端调用；Token 不得放进网页前端。</small></div><span className="connection-scope">{current?.api_address_scope==='same_host'?'仅同机':current?.api_address_scope==='lan'?'局域网':'已配置入口'}</span></section>
  {current?.api_address_warning&&<p className="connection-warning"><Network size={16}/>{current.api_address_warning}</p>}
  {open&&<form className="target-form temporary-form integration-form" aria-label={editing?'编辑应用接入':'新增应用接入'} onSubmit={submit} onKeyDown={e=>{if(e.key==='Escape'&&!busy){e.preventDefault();reset()}}}>
   <label>应用名称<input required disabled={!!busy} placeholder="例如：销售线索系统" value={form.name} onChange={e=>setForm({...form,name:e.target.value})}/></label>
   <fieldset disabled={!!busy}><legend>调用能力</legend><div className="choice-grid">
    <label className={`choice-card ${form.permission_preset==='notification'?'selected':''}`}><input type="radio" name="permission-preset" checked={form.permission_preset==='notification'} onChange={()=>selectPermissionPreset('notification')}/><span><b>通知应用（推荐）</b><small>读取用户对象、发送通知并查询逐微信结果</small></span></label>
    <label className={`choice-card ${form.permission_preset==='query'?'selected':''}`}><input type="radio" name="permission-preset" checked={form.permission_preset==='query'} onChange={()=>selectPermissionPreset('query')}/><span><b>只读查询</b><small>只能读取用户对象和发送预览</small></span></label>
    <label className={`choice-card ${form.permission_preset==='custom'?'selected':''}`}><input type="radio" name="permission-preset" checked={form.permission_preset==='custom'} onChange={()=>selectPermissionPreset('custom')}/><span><b>自定义权限</b><small>按实际用途进行最小授权</small></span></label>
   </div>{form.permission_preset==='custom'&&<div className="check-grid">{permissionOrder.map(value=><label className="check" key={value}><input type="checkbox" checked={form.permissions.includes(value)} onChange={()=>setForm({...form,permissions:toggle(form.permissions,value)})}/>{permissionLabels[value]}</label>)}</div>}</fieldset>
   <fieldset disabled={!!busy}><legend>允许的用户对象</legend><div className="scope-options">
    <label className="check"><input type="radio" name="object-scope" checked={form.object_scope==='selected'} onChange={()=>setForm({...form,object_scope:'selected'})}/>只允许指定对象</label>
    <label className="check"><input type="radio" name="object-scope" checked={form.object_scope==='all'} onChange={()=>setForm({...form,object_scope:'all'})}/>允许公司全部对象，包括未来新增对象</label>
   </div>{form.object_scope==='selected'&&<div className="object-picker">{userObjects.length?userObjects.map(item=><label className="check" key={item.user_object_code}><input type="checkbox" checked={form.allowed_target_codes.includes(item.user_object_code)} onChange={()=>setForm({...form,allowed_target_codes:toggle(form.allowed_target_codes,item.user_object_code)})}/><span><b>{item.account_name}{item.enabled?'':'（已停用）'}</b><code>{item.user_object_code}</code><small>已绑定 {item.bound_count} · 待绑定 {item.pending_count} · 异常 {item.unhealthy_count}</small></span></label>):<p className="muted">当前公司还没有用户对象；可明确选择“允许公司全部对象”后先创建接入。</p>}</div>}</fieldset>
   {error&&<p className="form-error" role="alert">{error}。已保留输入，请检查权限和对象后重试。</p>}<div className="form-actions"><button className="primary" type="submit" disabled={!!busy}>{busy==='save'?'保存中…':editing?'保存修改':'创建并显示接入凭据'}</button><button className="ghost" type="button" onClick={reset} disabled={!!busy}>取消</button></div>
  </form>}
  {!open&&error&&<p className="form-error" role="alert">{error}。请刷新状态后重试。</p>}
  <div className="card-list">{clients.length?clients.map(c=><article className="item-card api-client" key={c.id}><div><b>{c.name}</b><code>{c.token_prefix}…</code><small>权限：{c.permissions.map(value=>permissionLabels[value]||value).join('、')||'无'}</small><small>对象：{c.allowed_target_codes.length?c.allowed_target_codes.map(objectName).join('、'):'公司全部对象（含未来新增）'} · 最后调用 {time(c.last_used_at)}</small></div><Badge value={c.enabled?'active':'revoked'}/><div className="row-actions"><button type="button" className="ghost small" disabled={!c.enabled||!!busy} onClick={()=>void copyGuide(c)}>{busy===`guide:${c.id}`?'生成中…':<><Copy size={14}/>复制 AI 接入说明</>}</button><button type="button" className="ghost small" disabled={!c.enabled||!!busy} onClick={()=>beginEdit(c)}>编辑</button><button type="button" className="ghost small" disabled={!c.enabled||!!busy} onClick={()=>void rotate(c)}>{busy===`rotate:${c.id}`?'轮换中…':'轮换 Token'}</button><button type="button" className="ghost small danger" disabled={!!busy} onClick={()=>void remove(c)}>{busy===`delete:${c.id}`?'删除中…':'删除'}</button></div></article>):<Empty text="当前公司暂无接入应用"/>}</div>
 </Panel>
}

function BindingModal({initial,csrf,close,refresh,setPending,retryPath}:{initial:BindSession;csrf:string;close:()=>void;refresh:()=>Promise<void>;setPending:(value:boolean)=>void;retryPath:string}){
 const[s,setS]=useState(initial);const[error,setError]=useState('');const[busy,setBusy]=useState(false);const modalRef=useRef<HTMLElement>(null);const closeRef=useRef<HTMLButtonElement>(null);const mounted=useRef(true);const live=['pending','scanned','confirming'].includes(s.status)
 useEffect(()=>()=>{mounted.current=false},[])
 useEffect(()=>{closeRef.current?.focus();const onKey=(event:KeyboardEvent)=>{if(event.key==='Escape'&&!busy){event.preventDefault();close();return}if(event.key==='Tab'){const controls=Array.from(modalRef.current?.querySelectorAll<HTMLElement>('button:not(:disabled), [href], input:not(:disabled), select:not(:disabled), [tabindex]:not([tabindex="-1"])')||[]);if(!controls.length)return;const first=controls[0];const last=controls[controls.length-1];if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus()}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus()}}};window.addEventListener('keydown',onKey);return()=>window.removeEventListener('keydown',onKey)},[busy,close])
 useEffect(()=>{if(!live)return;let cancelled=false;let timer=0;let continuePolling=true;const poll=async()=>{try{const n=await api(`binding-sessions/${s.id}/poll`,write(csrf,'POST'));if(cancelled)return;continuePolling=['pending','scanned','confirming'].includes(n.status);setS(n);setError('');if(n.status==='bound')try{await refresh()}catch{if(mounted.current)setError('绑定已成功，但列表刷新失败，请手动刷新')}}catch(err){if(!cancelled)setError((err as Error).message)}finally{if(!cancelled&&continuePolling)timer=window.setTimeout(()=>void poll(),2000)}};timer=window.setTimeout(()=>void poll(),2000);return()=>{cancelled=true;window.clearTimeout(timer)}},[csrf,live,refresh,s.id])
 const cancel=async()=>{if(!confirm('确认取消本次等待绑定？二维码会立即失效，但不会解绑任何已绑定 Bot。'))return;setBusy(true);setPending(true);setError('');try{setS(await api(`binding-sessions/${s.id}/cancel`,write(csrf,'POST')));try{await refresh()}catch{setError('绑定等待已取消，但列表刷新失败，请稍后手动刷新')}}catch(err){setError((err as Error).message)}finally{setBusy(false);setPending(false)}}
 const retry=async()=>{setBusy(true);setPending(true);setError('');try{setS(await api(retryPath,write(csrf,'POST')))}catch(err){setError((err as Error).message)}finally{setBusy(false);setPending(false)}}
 return <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="微信 Bot 二维码绑定"><section ref={modalRef} className="binding-modal"><button ref={closeRef} type="button" className="modal-close" onClick={close} aria-label="关闭二维码"><X/></button><h3>使用个人微信扫码绑定独立 Bot</h3><Badge value={s.status}/>{live&&s.qr_image_url&&<img className="qr-image" src={s.qr_image_url} alt="微信 Bot 官方绑定二维码"/>}<p className="muted">二维码仅包含官方短时票据，不包含对象 ID 或 Bot 凭据。关闭窗口不会取消二维码。</p>{(error||s.failure_code)&&<p className="form-error" role="alert">{error||s.failure_code}。可稍后关闭，或在状态终止后刷新二维码重试。</p>}<div className="modal-actions">{live&&<button type="button" className="ghost danger" disabled={busy} onClick={()=>void cancel()}>{busy?'取消中…':'取消等待绑定'}</button>}{['expired','failed','cancelled'].includes(s.status)&&<button type="button" className="primary" disabled={busy} onClick={()=>void retry()}>{busy?'生成中…':'刷新二维码'}</button>}<button type="button" className="ghost" disabled={busy} onClick={close}>{s.status==='bound'?'完成并关闭':'稍后处理'}</button></div></section></div>
}
function BatchList({rows}:{rows:Batch[]}){return <div className="card-list">{rows.length?rows.map(b=><details className="batch-card" key={b.id}><summary><div><b>{b.title||'无标题通知'}</b><small>{time(b.created_at)} · 共 {b.total}，成功 {b.sent}，失败 {b.failed}，跳过 {b.skipped}</small></div><Badge value={b.status}/></summary><div className="delivery-grid">{b.deliveries.map(d=><div key={d.delivery_id}><code>{d.bot_masked}</code><Badge value={d.status}/><small>{d.failure_message||'—'}</small></div>)}</div></details>):<Empty text="当前公司暂无通知任务"/>}</div>}
function Panel({title,action,children}:{title:string;action?:React.ReactNode;children:React.ReactNode}){return <section className="panel"><div className="panel-head"><h3>{title}</h3>{action}</div>{children}</section>};function Stat({label,value}:{label:string;value:number}){return <div className="stat"><small>{label}</small><strong>{value}</strong></div>};function Badge({value}:{value:string}){return <span className={`badge ${value}`}>{labels[value]||value||'未知'}</span>};function Empty({text}:{text:string}){return <div className="empty"><BellRing/><b>{text}</b><p>可刷新页面，或使用上方操作开始配置。</p></div>};function time(value?:string){return value?new Date(value).toLocaleString():'—'}
