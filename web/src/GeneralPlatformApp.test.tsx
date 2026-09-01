// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { GeneralPlatformApp } from './GeneralPlatformApp'

type MockOptions = {
  companyCreateError?: string
  companyCreateGate?: Promise<void>
  bots?: Array<Record<string, unknown>>
  employees?: Array<Record<string, unknown>>
  clients?: Array<Record<string, unknown>>
  bindingPoll?: Record<string, unknown>
  failRefreshAfterBindingPoll?: boolean
  unauthorizedAfterToken?: boolean
  oldSessionUnauthorizedGate?: Promise<void>
  companyLoadErrorAfterCreate?: boolean
  tokenCreateGate?: Promise<void>
  tokenRotateGate?: Promise<void>
  userObjects?: Array<Record<string, unknown>>
  userObjectDetail?: Record<string, unknown>
}

function json(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  }))
}

function installApiMock(options: MockOptions = {}) {
  let companies = [
    { company_id: 'greenhome', company_slug: 'greenhome', name: '绿色家', enabled: true },
    { company_id: 'sanlin', company_slug: 'sanlin', name: '三林', enabled: true },
  ]
  let apiClients = options.clients || []
  let bindingPollSeen = false
  let tokenIssued = false
  let companyGetCount = 0
  let createdCompanyId = ''
  const integration = {
    api_base_url: 'https://notify.company.lan/notification-center/api/v1',
    api_address_scope: 'lan', api_address_warning: '',
    company_id: 'greenhome', company_slug: 'greenhome', company_name: '绿色家',
    client_id: 'client-1', client_name: '自动化客户端',
    permissions: ['query', 'send', 'status'], all_user_objects: true,
    allowed_user_objects: [], delivery_mode: 'weixin',
    guide_markdown: '# 微信通知平台接入说明\nToken 来自环境变量 EMPLOYEE_VIDEO_NOTIFICATION_API_TOKEN',
    curl_check: 'curl -fsS "$EMPLOYEE_VIDEO_NOTIFICATION_API/authorized-companies"',
  }
  const requests: Array<{ path: string; method: string; body?: unknown }> = []
  const mock = vi.fn((input: RequestInfo | URL, init: RequestInit = {}) => {
    const path = String(input).replace(/^api\/v1\//, '')
    const method = init.method || 'GET'
    const body = typeof init.body === 'string' ? JSON.parse(init.body) : undefined
    requests.push({ path, method, body })
    if (path === 'auth/session') return json({ csrf_token: 'csrf', role: 'super_admin' })
    if (path === 'companies' && method === 'GET') {
      companyGetCount += 1
      if (options.oldSessionUnauthorizedGate && companyGetCount === 3) {
        return options.oldSessionUnauthorizedGate.then(() => json({ detail: 'Authentication required' }, 401))
      }
      if (tokenIssued && options.unauthorizedAfterToken) {
        return json({ detail: 'Authentication required' }, 401)
      }
      if (bindingPollSeen && options.failRefreshAfterBindingPoll) {
        return json({ detail: 'isolated refresh failure' }, 503)
      }
      return json(companies)
    }
    if (path === 'companies' && method === 'POST') {
      const respond = () => {
        if (options.companyCreateError) return json({ detail: options.companyCreateError }, 409)
        const created = { company_id: body.company_slug, company_slug: body.company_slug, name: body.name, enabled: true }
        createdCompanyId = created.company_id
        companies = [...companies, created]
        return json(created, 201)
      }
      return options.companyCreateGate ? options.companyCreateGate.then(respond) : respond()
    }
    if (path === 'auth/logout' && method === 'POST') return json({ ok: true })
    if (path === 'auth/login' && method === 'POST') return json({ csrf_token: 'csrf-2', role: 'super_admin' })
    if (path.startsWith('notification-targets?')) {
      if (options.companyLoadErrorAfterCreate && createdCompanyId && path.includes(`company_id=${createdCompanyId}`)) {
        return json({ detail: 'isolated new-company refresh failure' }, 503)
      }
      return json([])
    }
    if (/^companies\/[^/]+\/user-objects$/.test(path) && method === 'GET') {
      if (options.companyLoadErrorAfterCreate && createdCompanyId && path.includes(`companies/${createdCompanyId}/`)) {
        return json({ detail: 'isolated new-company refresh failure' }, 503)
      }
      if (!path.includes('greenhome')) return json([])
      if (options.userObjects) return json(options.userObjects)
      return json(options.employees?.length ? [{ user_object_code: 'team-a', account_name: '员工对象', enabled: true, bound_count: 0, pending_count: 1, unhealthy_count: 0 }] : [])
    }
    if (path === 'companies/greenhome/user-objects/team-a' && method === 'GET') {
      if (options.userObjectDetail) return json(options.userObjectDetail)
      const employee = options.employees?.[0]
      const bot = options.bots?.[0]
      return json(options.userObjects?.[0] || {
        user_object_code: 'team-a', account_name: '员工对象', enabled: true, bound_count: 0, pending_count: 1, unhealthy_count: 0,
        contacts: employee ? [{
          employee_id: employee.id, name: employee.name, status: employee.status,
          binding: bot?.active ? { binding_id: bot.binding_id, status: 'bound', health_status: bot.health_status } : undefined,
          binding_session: employee.binding_session,
        }] : [],
      })
    }
    if (path === 'companies/greenhome/user-objects' && method === 'POST') {
      return json({ user_object_code: 'created-object', account_name: body.account_name, enabled: true }, 201)
    }
    if (path === 'companies/greenhome/user-objects/team-a/contacts' && method === 'POST') {
      return json({ employee_id: 'employee-new', ...body }, 201)
    }
    if (path === 'companies/greenhome/user-objects/team-a/bind-all' && method === 'POST') return json({ ok: true })
    if (path.startsWith('weixin-bots?')) return json(options.bots || [])
    if (path.startsWith('employees?')) return json(options.employees || [])
    if (path.startsWith('notification-batches?')) return json([])
    if (path.startsWith('api-clients?')) return json(apiClients)
    if (path === 'api-clients' && method === 'POST') {
      tokenIssued = true
      const respond = () => json({ id: 'client-1', name: body.name, token_prefix: 'evnc_test', permissions: body.permissions, allowed_target_codes: body.allowed_target_codes, enabled: true, token: 'one-time-test-token', integration }, 201)
      return options.tokenCreateGate ? options.tokenCreateGate.then(respond) : respond()
    }
    if (path === 'api-clients/client-1/integration-guide' && method === 'GET') return json(integration)
    if (path === 'api-clients/client-1' && method === 'DELETE') {
      apiClients = apiClients.filter(client => client.id !== 'client-1')
      return json({ ok: true, deleted_id: 'client-1', detached_notification_batches: 0 })
    }
    if (path.endsWith('/rotate') && method === 'POST') {
      const respond = () => json({ id: 'client-1', name: '现有客户端', token_prefix: 'evnc_rotated', permissions: ['query'], allowed_target_codes: [], enabled: true, token: 'rotated-one-time-test-token', integration })
      return options.tokenRotateGate ? options.tokenRotateGate.then(respond) : respond()
    }
    if (path.endsWith('/binding-sessions') && method === 'POST') {
      return json({ id: 'session-1', employee_id: 'employee-1', status: 'pending', qr_image_url: 'qr.png' }, 201)
    }
    if (path === 'binding-sessions/session-1/poll' && method === 'POST') {
      bindingPollSeen = true
      return json(options.bindingPoll || { id: 'session-1', employee_id: 'employee-1', status: 'pending', qr_image_url: 'qr.png' })
    }
    throw new Error(`Unexpected request: ${method} ${path}`)
  })
  vi.stubGlobal('fetch', mock)
  return { requests }
}

async function openSection(name: string) {
  const button = await screen.findByRole('button', { name })
  await waitFor(() => expect(button).toBeEnabled())
  await userEvent.click(button)
}

async function openCompanyForm() {
  await openSection('公司管理')
  await userEvent.click(await screen.findByRole('button', { name: '新增公司' }))
  return screen.getByRole('form', { name: '新增公司' })
}

describe('GeneralPlatformApp temporary workflow safety', () => {
  beforeEach(() => {
    vi.stubGlobal('confirm', vi.fn(() => true))
  })

  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('cancels company creation without a request and reopens blank', async () => {
    const { requests } = installApiMock()
    render(<GeneralPlatformApp />)
    const form = await openCompanyForm()
    await userEvent.type(within(form).getByLabelText('公司标识'), 'draft-company')
    await userEvent.type(within(form).getByLabelText('公司名称'), '临时公司')
    await userEvent.click(within(form).getByRole('button', { name: '取消' }))

    expect(screen.queryByRole('form', { name: '新增公司' })).not.toBeInTheDocument()
    expect(requests.filter(r => r.method === 'POST' && r.path === 'companies')).toHaveLength(0)

    const reopened = await openCompanyForm()
    expect(within(reopened).getByLabelText('公司标识')).toHaveValue('')
    expect(within(reopened).getByLabelText('公司名称')).toHaveValue('')
  })

  it('closes, resets, and selects a successfully created company', async () => {
    installApiMock()
    render(<GeneralPlatformApp />)
    const form = await openCompanyForm()
    await userEvent.type(within(form).getByLabelText('公司标识'), 'acme')
    await userEvent.type(within(form).getByLabelText('公司名称'), '示例公司')
    await userEvent.click(within(form).getByRole('button', { name: '创建公司' }))

    await waitFor(() => expect(screen.queryByRole('form', { name: '新增公司' })).not.toBeInTheDocument())
    await waitFor(() => expect(screen.getByLabelText('当前公司')).toHaveValue('acme'))
    const reopened = await openCompanyForm()
    expect(within(reopened).getByLabelText('公司标识')).toHaveValue('')
    expect(within(reopened).getByLabelText('公司名称')).toHaveValue('')
  })

  it('keeps company-create success explicit when loading the new tenant fails', async () => {
    const { requests } = installApiMock({ companyLoadErrorAfterCreate: true })
    render(<GeneralPlatformApp />)
    const form = await openCompanyForm()
    await userEvent.type(within(form).getByLabelText('公司标识'), 'refresh-fail-company')
    await userEvent.type(within(form).getByLabelText('公司名称'), '已创建公司')
    await userEvent.click(within(form).getByRole('button', { name: '创建公司' }))

    expect(await screen.findByRole('status')).toHaveTextContent('公司创建成功')
    expect(await screen.findByRole('alert')).toHaveTextContent('公司已创建，但新公司数据刷新失败')
    expect(screen.queryByRole('form', { name: '新增公司' })).not.toBeInTheDocument()
    expect(requests.filter(r => r.method === 'POST' && r.path === 'companies')).toHaveLength(1)
  })

  it('preserves company input and shows an actionable creation failure', async () => {
    installApiMock({ companyCreateError: '公司标识已存在，请更换后重试' })
    render(<GeneralPlatformApp />)
    const form = await openCompanyForm()
    await userEvent.type(within(form).getByLabelText('公司标识'), 'acme')
    await userEvent.type(within(form).getByLabelText('公司名称'), '示例公司')
    await userEvent.click(within(form).getByRole('button', { name: '创建公司' }))

    expect(await within(form).findByRole('alert')).toHaveTextContent('公司标识已存在，请更换后重试')
    expect(within(form).getByLabelText('公司标识')).toHaveValue('acme')
    expect(within(form).getByLabelText('公司名称')).toHaveValue('示例公司')
    expect(within(form).getByRole('button', { name: '创建公司' })).toBeEnabled()
  })

  it('locks tenant switching, navigation, and logout while a write is pending', async () => {
    let release!: () => void
    const gate = new Promise<void>(resolve => { release = resolve })
    installApiMock({ companyCreateGate: gate })
    render(<GeneralPlatformApp />)
    const form = await openCompanyForm()
    await userEvent.type(within(form).getByLabelText('公司标识'), 'locked-company')
    await userEvent.type(within(form).getByLabelText('公司名称'), '锁定测试')
    await userEvent.click(within(form).getByRole('button', { name: '创建公司' }))

    expect(screen.getByLabelText('当前公司')).toBeDisabled()
    expect(screen.getByRole('button', { name: '用户对象' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '退出登录' })).toBeDisabled()
    expect(within(form).getByRole('button', { name: '保存中…' })).toBeDisabled()
    release()
    await waitFor(() => expect(screen.getByLabelText('当前公司')).toHaveValue('locked-company'))
  })

  it('clears a user-object draft when switching company without creating anything', async () => {
    const { requests } = installApiMock()
    render(<GeneralPlatformApp />)
    await openSection('用户对象')
    await userEvent.click(screen.getByRole('button', { name: '创建用户对象' }))
    await userEvent.type(screen.getByLabelText('账号名称'), '公司 A 草稿')
    await userEvent.selectOptions(screen.getByLabelText('当前公司'), 'sanlin')

    await waitFor(() => expect(screen.queryByRole('form', { name: '新增用户对象' })).not.toBeInTheDocument())
    await userEvent.click(screen.getByRole('button', { name: '创建用户对象' }))
    expect(screen.getByLabelText('账号名称')).toHaveValue('')
    expect(requests.filter(r => r.method === 'POST' && r.path.endsWith('/user-objects'))).toHaveLength(0)
  })

  it('cancels target and API client drafts without write requests', async () => {
    const { requests } = installApiMock()
    render(<GeneralPlatformApp />)
    await openSection('用户对象')
    await userEvent.click(screen.getByRole('button', { name: '创建用户对象' }))
    await userEvent.type(screen.getByLabelText('账号名称'), '草稿对象')
    await userEvent.click(screen.getByRole('button', { name: '取消' }))
    expect(screen.queryByRole('form', { name: '新增用户对象' })).not.toBeInTheDocument()

    await openSection('应用接入')
    await userEvent.click(screen.getByRole('button', { name: '接入新应用' }))
    await userEvent.type(screen.getByLabelText('应用名称'), '草稿客户端')
    await userEvent.click(screen.getByRole('button', { name: '取消' }))
    expect(screen.queryByRole('form', { name: '新增应用接入' })).not.toBeInTheDocument()
    expect(requests.filter(r => r.method !== 'GET' && !r.path.startsWith('auth/'))).toHaveLength(0)
  })

  it('keeps a newly issued one-time token visible after refreshing client data', async () => {
    installApiMock()
    render(<GeneralPlatformApp />)
    await openSection('应用接入')
    await userEvent.click(screen.getByRole('button', { name: '接入新应用' }))
    await userEvent.type(screen.getByLabelText('应用名称'), '自动化客户端')
    await userEvent.click(screen.getByRole('button', { name: '创建并显示接入凭据' }))

    expect(await screen.findByText('one-time-test-token')).toBeVisible()
    expect(screen.getByRole('button', { name: '关闭一次性 Token' })).toBeEnabled()
    expect(screen.getByRole('button', { name: '总览' })).toBeDisabled()
    expect(screen.getByLabelText('当前公司')).toBeDisabled()
    expect(screen.getByRole('button', { name: '退出登录' })).toBeDisabled()
    await userEvent.click(screen.getByRole('button', { name: '关闭一次性 Token' }))
    expect(screen.getByRole('button', { name: '总览' })).toBeEnabled()
    expect(screen.getByLabelText('当前公司')).toBeEnabled()
    expect(screen.getByRole('button', { name: '退出登录' })).toBeEnabled()
  })

  it('defaults a new notification app to the complete workflow and one explicit object', async () => {
    const { requests } = installApiMock({
      userObjects: [{
        user_object_code: 'team-a', account_name: '客服组', enabled: true,
        bound_count: 2, pending_count: 0, unhealthy_count: 0,
      }],
    })
    render(<GeneralPlatformApp />)
    await openSection('应用接入')
    await userEvent.click(screen.getByRole('button', { name: '接入新应用' }))
    const form = screen.getByRole('form', { name: '新增应用接入' })

    expect(within(form).getByRole('radio', { name: /通知应用/ })).toBeChecked()
    expect(within(form).getByRole('radio', { name: '只允许指定对象' })).toBeChecked()
    expect(within(form).getByRole('checkbox', { name: /客服组/ })).toBeChecked()
    await userEvent.type(within(form).getByLabelText('应用名称'), '销售通知系统')
    await userEvent.click(within(form).getByRole('button', { name: '创建并显示接入凭据' }))

    await waitFor(() => expect(requests).toContainEqual({
      path: 'api-clients', method: 'POST',
      body: {
        company_id: 'greenhome', name: '销售通知系统',
        permissions: ['query', 'send', 'status'], allowed_target_codes: ['team-a'],
      },
    }))
  })

  it('copies an AI guide without copying the one-time token', async () => {
    const writeText = vi.fn(async (_value: string) => {})
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } })
    installApiMock()
    render(<GeneralPlatformApp />)
    await openSection('应用接入')
    await userEvent.click(screen.getByRole('button', { name: '接入新应用' }))
    await userEvent.type(screen.getByLabelText('应用名称'), '安全接入测试')
    await userEvent.click(screen.getByRole('button', { name: '创建并显示接入凭据' }))
    await userEvent.click(await screen.findByRole('button', { name: '一键复制 AI 接入说明' }))

    expect(writeText).toHaveBeenCalledWith(expect.stringContaining('EMPLOYEE_VIDEO_NOTIFICATION_API_TOKEN'))
    expect(writeText.mock.calls[0][0]).not.toContain('one-time-test-token')
    expect(await screen.findByText('AI 接入说明已复制')).toBeVisible()
  })

  it('protects a rotated one-time token until it is explicitly acknowledged', async () => {
    installApiMock({
      clients: [{
        id: 'client-1', name: '现有客户端', token_prefix: 'evnc_existing',
        permissions: ['query'], allowed_target_codes: [], enabled: true,
      }],
    })
    render(<GeneralPlatformApp />)
    await openSection('应用接入')
    await userEvent.click(await screen.findByRole('button', { name: '轮换 Token' }))

    expect(await screen.findByText('rotated-one-time-test-token')).toBeVisible()
    expect(screen.getByRole('button', { name: '总览' })).toBeDisabled()
    expect(screen.getByLabelText('当前公司')).toBeDisabled()
    expect(screen.getByRole('button', { name: '退出登录' })).toBeDisabled()
  })

  it('permanently deletes an API client instead of retaining a revoked card', async () => {
    const { requests } = installApiMock({
      clients: [{
        id: 'client-1', name: '待删除应用', token_prefix: 'evnc_existing',
        permissions: ['query'], allowed_target_codes: [], enabled: false,
      }],
    })
    render(<GeneralPlatformApp />)
    await openSection('应用接入')
    expect(await screen.findByText('待删除应用')).toBeVisible()

    await userEvent.click(screen.getByRole('button', { name: '删除' }))

    await waitFor(() => expect(screen.queryByText('待删除应用')).not.toBeInTheDocument())
    expect(requests).toContainEqual({
      path: 'api-clients/client-1', method: 'DELETE', body: { confirm: true },
    })
    expect(await screen.findByText('应用接入已永久删除。')).toBeVisible()
  })

  it('preserves a one-time token on session expiry and blocks re-login until acknowledgement', async () => {
    installApiMock({ unauthorizedAfterToken: true })
    render(<GeneralPlatformApp />)
    await openSection('应用接入')
    await userEvent.click(screen.getByRole('button', { name: '接入新应用' }))
    await userEvent.type(screen.getByLabelText('应用名称'), '会话失效客户端')
    await userEvent.click(screen.getByRole('button', { name: '创建并显示接入凭据' }))

    expect(await screen.findByText('one-time-test-token')).toBeVisible()
    expect(screen.getByRole('heading', { name: '会话已失效' })).toBeVisible()
    expect(screen.queryByRole('button', { name: '安全登录' })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '确认已保存并返回登录' }))
    expect(await screen.findByRole('button', { name: '安全登录' })).toBeVisible()
    expect(screen.queryByText('one-time-test-token')).not.toBeInTheDocument()
  })

  it('ignores a delayed unauthorized response from the previous session after re-login', async () => {
    let releaseOldRequest!: () => void
    const oldRequestGate = new Promise<void>(resolve => { releaseOldRequest = resolve })
    installApiMock({ oldSessionUnauthorizedGate: oldRequestGate })
    render(<GeneralPlatformApp />)
    await screen.findByText('绿色家')
    const refresh = await screen.findByRole('button', { name: '刷新' })
    await waitFor(() => expect(refresh).toBeEnabled())
    await userEvent.click(refresh)

    await act(async () => {
      window.dispatchEvent(new Event('evnc:unauthorized'))
    })
    await userEvent.type(screen.getByLabelText('用户名'), 'new-session-admin')
    await userEvent.type(screen.getByLabelText('密码'), 'new-session-password')
    await userEvent.click(screen.getByRole('button', { name: '安全登录' }))
    expect(await screen.findByRole('button', { name: '退出登录' })).toBeVisible()

    await act(async () => {
      releaseOldRequest()
      await oldRequestGate
      await Promise.resolve()
    })
    await waitFor(() => expect(screen.getByRole('button', { name: '退出登录' })).toBeVisible())
    expect(screen.queryByRole('button', { name: '安全登录' })).not.toBeInTheDocument()
  })

  it('preserves a delayed one-time token response and blocks re-login until acknowledgement', async () => {
    let releaseToken!: () => void
    const tokenGate = new Promise<void>(resolve => { releaseToken = resolve })
    installApiMock({ tokenCreateGate: tokenGate })
    render(<GeneralPlatformApp />)
    await openSection('应用接入')
    await userEvent.click(screen.getByRole('button', { name: '接入新应用' }))
    await userEvent.type(screen.getByLabelText('应用名称'), '旧身份客户端')
    await userEvent.click(screen.getByRole('button', { name: '创建并显示接入凭据' }))

    await act(async () => {
      window.dispatchEvent(new Event('evnc:unauthorized'))
    })
    expect(await screen.findByRole('heading', { name: '会话已失效' })).toBeVisible()
    expect(screen.getByRole('status')).toHaveTextContent('一次性 Token 请求仍在完成中')
    expect(screen.queryByRole('button', { name: '安全登录' })).not.toBeInTheDocument()

    await act(async () => {
      releaseToken()
      await tokenGate
      await Promise.resolve()
    })
    expect(await screen.findByText('one-time-test-token')).toBeVisible()
    expect(screen.queryByRole('button', { name: '安全登录' })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '确认已保存并返回登录' }))
    expect(await screen.findByRole('button', { name: '安全登录' })).toBeVisible()
  })

  it('preserves a delayed rotated token after session expiry', async () => {
    let releaseToken!: () => void
    const tokenGate = new Promise<void>(resolve => { releaseToken = resolve })
    installApiMock({
      tokenRotateGate: tokenGate,
      clients: [{
        id: 'client-1', name: '待轮换客户端', token_prefix: 'evnc_existing',
        permissions: ['query'], allowed_target_codes: [], enabled: true,
      }],
    })
    render(<GeneralPlatformApp />)
    await openSection('应用接入')
    await userEvent.click(await screen.findByRole('button', { name: '轮换 Token' }))
    await act(async () => {
      window.dispatchEvent(new Event('evnc:unauthorized'))
    })
    expect(await screen.findByRole('status')).toHaveTextContent('一次性 Token 请求仍在完成中')
    expect(screen.queryByRole('button', { name: '安全登录' })).not.toBeInTheDocument()

    await act(async () => {
      releaseToken()
      await tokenGate
      await Promise.resolve()
    })
    expect(await screen.findByText('rotated-one-time-test-token')).toBeVisible()
    expect(screen.queryByRole('button', { name: '安全登录' })).not.toBeInTheDocument()
  })

  it('closes a binding QR with Escape without cancelling the server session and restores focus', async () => {
    const { requests } = installApiMock({
      bots: [{
        bot_id: 'bot-1', binding_id: 'binding-1', owner_target_id: 'employee-1',
        owner_display_name: '员工甲', bot_masked: 'bot***1', active: false,
        health_status: 'unknown', bound_at: '2026-01-01T00:00:00Z',
      }],
      employees: [{ id: 'employee-1', name: '员工甲', status: 'active' }],
    })
    render(<GeneralPlatformApp />)
    await openSection('用户对象')
    await userEvent.click(await screen.findByRole('button', { name: '展开员工对象详情' }))
    const trigger = await screen.findByRole('button', { name: '生成二维码' })
    await userEvent.click(trigger)
    expect(await screen.findByRole('dialog', { name: '微信 Bot 二维码绑定' })).toBeInTheDocument()
    requests.splice(0)
    await userEvent.keyboard('{Escape}')

    expect(screen.queryByRole('dialog', { name: '微信 Bot 二维码绑定' })).not.toBeInTheDocument()
    expect(requests.some(r => r.path.includes('/cancel'))).toBe(false)
    expect(trigger).toHaveFocus()
  })

  it('reopens an existing live contact binding session without creating a replacement', async () => {
    const bindingSession = {
      id: 'session-1', employee_id: 'employee-1', status: 'pending', qr_image_url: 'qr.png',
    }
    const { requests } = installApiMock({
      employees: [{
        id: 'employee-1', name: '员工甲', status: 'active', binding_session: bindingSession,
      }],
    })
    render(<GeneralPlatformApp />)
    await openSection('用户对象')
    await userEvent.click(await screen.findByRole('button', { name: '展开员工对象详情' }))
    const resume = await screen.findByRole('button', { name: '查看二维码' })
    requests.splice(0)

    await userEvent.click(resume)
    expect(await screen.findByRole('dialog', { name: '微信 Bot 二维码绑定' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '稍后处理' }))
    await userEvent.click(screen.getByRole('button', { name: '查看二维码' }))

    expect(await screen.findByRole('dialog', { name: '微信 Bot 二维码绑定' })).toBeInTheDocument()
    expect(requests.filter(request => request.method === 'POST' && request.path.endsWith('/binding-sessions'))).toHaveLength(0)
  })

  it('reports a successful binding separately when the follow-up refresh fails', async () => {
    installApiMock({
      bots: [{
        bot_id: 'bot-1', binding_id: 'binding-1', owner_target_id: 'employee-1',
        owner_display_name: '员工甲', bot_masked: 'bot***1', active: false,
        health_status: 'unknown', bound_at: '2026-01-01T00:00:00Z',
      }],
      employees: [{ id: 'employee-1', name: '员工甲', status: 'active' }],
      bindingPoll: { id: 'session-1', employee_id: 'employee-1', status: 'bound' },
      failRefreshAfterBindingPoll: true,
    })
    render(<GeneralPlatformApp />)
    await openSection('用户对象')
    await userEvent.click(await screen.findByRole('button', { name: '展开员工对象详情' }))
    await userEvent.click(await screen.findByRole('button', { name: '生成二维码' }))
    expect(await screen.findByRole('dialog', { name: '微信 Bot 二维码绑定' })).toBeInTheDocument()

    expect(await screen.findByRole('alert', {}, { timeout: 3500 })).toHaveTextContent('绑定已成功，但列表刷新失败')
    expect(screen.getByText('绑定成功')).toBeVisible()
  })

  it('clears all tenant data on explicit logout', async () => {
    installApiMock()
    render(<GeneralPlatformApp />)
    await screen.findByText('绿色家')
    await userEvent.click(screen.getByRole('button', { name: '退出登录' }))

    expect(await screen.findByRole('button', { name: '安全登录' })).toBeVisible()
    expect(screen.queryByText('绿色家')).not.toBeInTheDocument()
    expect(screen.queryByText('三林')).not.toBeInTheDocument()
  })
})

describe('merged user object management', () => {
  beforeEach(() => vi.stubGlobal('confirm', vi.fn(() => true)))
  afterEach(() => { cleanup(); vi.unstubAllGlobals() })

  const object = {
    user_object_code: 'team-a', account_name: '客服组', enabled: true,
    bound_count: 1, pending_count: 1, unhealthy_count: 1,
    last_test_at: '2026-08-20T08:00:00Z', all_available: true,
  }
  const detail = {
    ...object,
    contacts: [{
      employee_id: 'employee-1', name: '员工甲', masked_phone: '138****8000',
      status: 'active', binding: { binding_id: 'binding-1', status: 'bound', health_status: 'degraded', bot_masked: 'bot***1', manual_test: { allowed: true } },
    }],
  }

  it('uses one user-object navigation destination and removes the standalone Bot page', async () => {
    installApiMock({ userObjects: [object] })
    render(<GeneralPlatformApp />)
    expect(await screen.findByRole('button', { name: '用户对象' })).toBeVisible()
    expect(screen.queryByRole('button', { name: '通知对象' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '微信 Bot' })).not.toBeInTheDocument()
  })

  it('shows object health at a glance and expands company-scoped contact details', async () => {
    const { requests } = installApiMock({ userObjects: [object], userObjectDetail: detail })
    render(<GeneralPlatformApp />)
    await openSection('用户对象')
    expect(await screen.findByText('已绑定 1')).toBeVisible()
    expect(screen.getByText('待绑定 1')).toBeVisible()
    expect(screen.getByText('异常 1')).toBeVisible()
    await userEvent.click(screen.getByRole('button', { name: '展开客服组详情' }))
    expect(await screen.findByText('138****8000')).toBeVisible()
    expect(screen.getByText('员工甲')).toBeVisible()
    expect(requests.some(r => r.path === 'companies/greenhome/user-objects/team-a')).toBe(true)
    expect(screen.getByRole('button', { name: '逐 Bot 安全测试' })).toBeVisible()
    expect(screen.getByRole('button', { name: '解绑' })).toBeVisible()
  })

  it('does not offer the server-rejected rebind action for an active binding', async () => {
    installApiMock({ userObjects: [object], userObjectDetail: detail })
    render(<GeneralPlatformApp />)
    await openSection('用户对象')
    await userEvent.click(await screen.findByRole('button', { name: '展开客服组详情' }))
    expect(await screen.findByRole('button', { name: '解绑' })).toBeVisible()
    expect(screen.queryByRole('button', { name: '重新绑定' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '生成二维码' })).not.toBeInTheDocument()
  })

  it('sends explicit server confirmation when deactivating a user object', async () => {
    const managedObject = { ...object, all_available: false }
    const managedDetail = { ...detail, all_available: false }
    const { requests } = installApiMock({ userObjects: [managedObject], userObjectDetail: managedDetail })
    render(<GeneralPlatformApp />)
    await openSection('用户对象')
    await userEvent.click(await screen.findByRole('button', { name: '展开客服组详情' }))
    await userEvent.click(await screen.findByRole('button', { name: '停用' }))
    await waitFor(() => expect(requests).toContainEqual({
      path: 'companies/greenhome/user-objects/team-a', method: 'PATCH',
      body: { enabled: false, confirm: true },
    }))
  })

  it('creates an object with account name only and does not expose code or mode', async () => {
    const { requests } = installApiMock()
    render(<GeneralPlatformApp />)
    await openSection('用户对象')
    await userEvent.click(screen.getByRole('button', { name: '创建用户对象' }))
    const form = screen.getByRole('form', { name: '新增用户对象' })
    expect(within(form).getByLabelText('账号名称')).toBeVisible()
    expect(within(form).queryByText(/target_code|模式|single|multi|dynamic_all/)).not.toBeInTheDocument()
    await userEvent.type(within(form).getByLabelText('账号名称'), '新账号')
    await userEvent.click(within(form).getByRole('button', { name: '创建' }))
    await waitFor(() => expect(requests).toContainEqual({
      path: 'companies/greenhome/user-objects', method: 'POST', body: { account_name: '新账号' },
    }))
  })

  it('adds a contact inline and binds every available Bot for a managed object', async () => {
    const managedObject = { ...object, all_available: false }
    const managedDetail = { ...detail, all_available: false }
    const { requests } = installApiMock({ userObjects: [managedObject], userObjectDetail: managedDetail })
    render(<GeneralPlatformApp />)
    await openSection('用户对象')
    await userEvent.click(await screen.findByRole('button', { name: '展开客服组详情' }))
    await screen.findByText('138****8000')
    await userEvent.click(screen.getByRole('button', { name: '添加联系人' }))
    const form = screen.getByRole('form', { name: '添加联系人' })
    await userEvent.type(within(form).getByLabelText('姓名'), '员工乙')
    await userEvent.type(within(form).getByLabelText('电话'), '13900001111')
    await userEvent.click(within(form).getByRole('button', { name: '保存联系人' }))
    await waitFor(() => expect(requests).toContainEqual({
      path: 'companies/greenhome/user-objects/team-a/contacts', method: 'POST',
      body: { name: '员工乙', phone: '13900001111' },
    }))
    await userEvent.click(screen.getByRole('button', { name: '展开客服组详情' }))
    await screen.findByRole('button', { name: '绑定全部可用 Bot' })
    await userEvent.click(screen.getByRole('button', { name: '绑定全部可用 Bot' }))
    expect(requests.some(r => r.path.endsWith('/bind-all') && r.method === 'POST')).toBe(true)
  })
})
