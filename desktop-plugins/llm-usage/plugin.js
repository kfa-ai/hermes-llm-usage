/**
 * LLM Usage — Hermes Desktop plugin
 *
 * Floating HUD (close via header ✕; reopen from status-bar chip):
 *   Claude Code — Session / All models / Fable
 *   Grok        — Weekly
 *   Codex       — 5-hour / weekly
 *   Venice      — DIEM epoch / USD balance
 *
 * Account plan windows / balances only — never API-key caps as balances.
 */

import {
  Button,
  Codicon,
  EmptyState,
  ErrorState,
  GlyphSpinner,
  PALETTE_AREA,
  ROUTES_AREA,
  SIDEBAR_NAV_AREA,
  ScrollArea,
  StatusDot,
  Tip,
  atom,
  cn,
  haptic,
  host,
  queryClient,
  useQuery,
  useValue,
} from '@hermes/plugin-sdk'
import { useState } from 'react'
import { jsx, jsxs } from 'react/jsx-runtime'

const ID = 'llm-usage'
const ROUTE = '/llm-usage'
const REST_TIMEOUT_MS = 90_000
const OPEN_STORAGE_KEY = 'floatingOpen'
const QUERY_KEY = [ID, 'usage']

/** Shared open-state for the floating card (chip ↔ close button). */
const $floatingOpen = atom(true)

/** @typedef {{ label: string, used_pct: number, reset_label?: string | null, id?: string }} QuotaWindow */
/** @typedef {{
 *   id: string,
 *   name: string,
 *   status?: string,
 *   windows?: QuotaWindow[],
 *   error?: string | null,
 *   note?: string | null,
 *   capacity?: Record<string, unknown> | null
 * }} Provider */

function shortLabel(window) {
  const id = window.id || ''
  if (id === 'session' || /session/i.test(window.label)) return 'Session'
  if (id === 'fable' || /fable/i.test(window.label)) return 'Fable'
  if (id === 'all_models' || /all models/i.test(window.label)) return 'All models'
  if (id === 'weekly' || /weekly/i.test(window.label)) return 'Weekly'
  if (id === 'five_hour' || /5-hour/i.test(window.label)) return '5-hour'
  if (id === 'diem_epoch') return 'DIEM epoch'
  if (id === 'usd_balance') return 'USD balance'
  return (
    window.label
      .replace(/^Current\s+(week|session)\s*/i, '')
      .replace(/^\(|\)$/g, '')
      .replace(/^Weekly\s+/i, '')
      .replace(/\s*Codex$/i, '') || window.label
  )
}

function orderWindows(providerId, windows) {
  const rank = (w) => {
    const id = w.id || ''
    if (providerId === 'anthropic') {
      if (id === 'session') return 0
      if (id === 'all_models') return 1
      if (id === 'fable') return 2
    }
    if (providerId === 'codex') {
      if (id === 'five_hour') return 0
      if (id === 'weekly') return 1
    }
    return 3
  }
  return [...(windows || [])].sort((a, b) => rank(a) - rank(b))
}

function statusTone(used) {
  if (used >= 90) return 'bad'
  if (used >= 75) return 'warn'
  return 'good'
}

function toneColor(used) {
  if (used >= 90) return 'var(--ui-danger, var(--destructive, var(--ui-accent)))'
  if (used >= 75) return 'var(--ui-warning, var(--ui-accent))'
  return 'var(--ui-accent)'
}

function formatRefresh(iso) {
  if (!iso) return ''
  try {
    return new Date(iso).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
  } catch {
    return ''
  }
}

function formatReset(reset) {
  if (!reset) return ''
  return reset.replace(/\s*\([^)]*\)\s*$/, '').trim()
}

function fetchUsage(rest, force = false) {
  return rest(force ? '/usage?force=true' : '/usage', { timeoutMs: REST_TIMEOUT_MS })
}

async function refreshUsage(rest) {
  const payload = await fetchUsage(rest, true)
  queryClient.setQueryData(QUERY_KEY, payload)
  return payload
}

function Meter({ used }) {
  return jsx('div', {
    role: 'meter',
    'aria-valuemin': 0,
    'aria-valuemax': 100,
    'aria-valuenow': Math.round(used),
    'aria-label': `${Math.round(used)} percent used`,
    className: 'h-1.5 w-full overflow-hidden rounded-full',
    style: {
      background: 'color-mix(in srgb, var(--ui-stroke-secondary) 60%, transparent)',
    },
    children: jsx('div', {
      className: 'h-full rounded-full transition-[width] duration-300 ease-out',
      style: {
        width: `${Math.max(0, Math.min(100, used))}%`,
        background: toneColor(used),
      },
    }),
  })
}

function CompactWindowRow({ window: w }) {
  const used = w.used_pct ?? 0
  const tone = statusTone(used)
  const reset = formatReset(w.reset_label)
  const isBalance = w.id === 'usd_balance'

  return jsxs('div', {
    className: 'flex flex-col gap-0.5 py-1',
    children: [
      jsxs('div', {
        className: 'flex items-center gap-1.5',
        children: [
          jsx(StatusDot, { tone: isBalance ? 'good' : tone }),
          jsx('span', {
            className: 'min-w-0 flex-1 truncate text-[0.75rem] font-medium',
            children: shortLabel(w),
          }),
          jsx('span', {
            className: 'shrink-0 text-[0.75rem] font-bold tabular-nums',
            style: { color: !isBalance && used >= 90 ? toneColor(used) : undefined },
            children: isBalance
              ? reset || '—'
              : used >= 100
                ? 'Maxed'
                : `${Math.round(used)}%`,
          }),
        ],
      }),
      isBalance ? null : jsx(Meter, { used }),
      !isBalance && reset
        ? jsx('div', {
            className: 'truncate pl-3.5 text-[0.625rem] text-(--ui-text-quaternary)',
            children: reset.startsWith('$') ? reset : `Resets ${reset}`,
          })
        : null,
    ],
  })
}

function ProviderSection({ provider }) {
  const windows = orderWindows(provider.id, provider.windows || [])
  const hasData = windows.length > 0
  const err = provider.error

  return jsxs('section', {
    className: 'flex flex-col gap-0.5',
    children: [
      jsxs('div', {
        className: 'flex items-baseline justify-between gap-2 pt-0.5',
        children: [
          jsx('h3', {
            className:
              'text-[0.625rem] font-semibold uppercase tracking-[0.08em] text-(--ui-text-quaternary)',
            children: provider.name,
          }),
          !hasData && err
            ? jsx('span', {
                className: 'truncate text-[0.625rem] text-(--ui-text-quaternary)',
                children: 'unavailable',
              })
            : null,
        ],
      }),
      hasData
        ? jsx('div', {
            className: 'flex flex-col',
            children: windows.map((w) =>
              jsx(CompactWindowRow, { window: w }, `${provider.id}:${w.id || w.label}`)
            ),
          })
        : jsx('div', {
            className: 'py-1 text-[0.6875rem] text-(--ui-text-quaternary)',
            children: err || 'No plan windows',
          }),
    ],
  })
}

function providersFromPayload(data) {
  if (data?.providers?.length) return data.providers
  if (data?.windows?.length) {
    return [
      {
        id: 'anthropic',
        name: 'Claude Code',
        windows: data.windows,
        error: data.error,
      },
    ]
  }
  return []
}

function worstAcross(providers) {
  let worst = null
  for (const p of providers) {
    for (const w of p.windows || []) {
      if (w.id === 'usd_balance') continue
      if (!worst || (w.used_pct || 0) > (worst.used_pct || 0)) {
        worst = { ...w, provider_name: p.name, provider_id: p.id }
      }
    }
  }
  return worst
}

function useUsage(rest) {
  return useQuery({
    queryKey: QUERY_KEY,
    queryFn: () => fetchUsage(rest, false),
    refetchInterval: 60_000,
    staleTime: 30_000,
    retry: 1,
  })
}

const headerBtnClass =
  'grid size-5 place-items-center rounded text-(--ui-text-quaternary) transition-colors hover:bg-(--chrome-action-hover) hover:text-(--ui-text-primary) disabled:opacity-50'

function FloatHeaderActions({ rest, onClose }) {
  const [busy, setBusy] = useState(false)
  const { isFetching } = useUsage(rest)
  const spinning = busy || isFetching

  return jsxs('div', {
    className: 'flex items-center gap-0.5',
    children: [
      jsx(Tip, {
        label: 'Refresh (CLI + API, can take ~15s)',
        children: jsx('button', {
          type: 'button',
          className: headerBtnClass,
          'data-floating-no-drag': '',
          'aria-label': 'Refresh LLM usage',
          disabled: spinning,
          onClick: () => {
            haptic('tap')
            setBusy(true)
            refreshUsage(rest)
              .catch((err) => host.notifyError(err, 'Could not refresh LLM usage'))
              .finally(() => setBusy(false))
          },
          children: jsx(Codicon, {
            name: 'refresh',
            size: '0.75rem',
            spinning,
          }),
        }),
      }),
      onClose
        ? jsx(Tip, {
            label: 'Close panel (reopen from status bar)',
            children: jsx('button', {
              type: 'button',
              className: headerBtnClass,
              'data-floating-no-drag': '',
              'aria-label': 'Close LLM usage',
              onClick: () => {
                haptic('tap')
                onClose()
              },
              children: jsx(Codicon, { name: 'close', size: '0.75rem' }),
            }),
          })
        : null,
    ],
  })
}

function UsageBoard({ rest, mode }) {
  const { data, isLoading, isFetching, error, refetch, isError } = useUsage(rest)
  const providers = providersFromPayload(data)
  const anyWindows = providers.some((p) => (p.windows || []).length > 0)
  const errMsg =
    (error && (error.message || String(error))) || data?.error || null
  const showError = (isError || Boolean(data?.error)) && !anyWindows
  const isPage = mode === 'page'
  const isFloat = mode === 'float'

  const onRefresh = () => {
    haptic('tap')
    refreshUsage(rest).catch((err) => host.notifyError(err, 'Could not refresh LLM usage'))
  }

  return jsxs('div', {
    className: cn(
      'flex h-full min-h-0 flex-col text-sm',
      isPage ? 'mx-auto w-full max-w-md gap-3 p-5' : 'gap-1.5 p-2'
    ),
    children: [
      // Page mode keeps an in-body toolbar; float mode uses headerActions.
      !isFloat
        ? jsxs('div', {
            className: 'flex items-center gap-1.5',
            children: [
              jsx('div', {
                className: 'min-w-0 flex-1 text-[0.6875rem] text-(--ui-text-quaternary)',
                children: isPage
                  ? jsxs('div', {
                      children: [
                        jsx('div', {
                          className: 'text-lg font-semibold tracking-tight text-foreground',
                          children: 'LLM Usage',
                        }),
                        jsx('div', {
                          children: 'Account plan windows · not API-key caps',
                        }),
                      ],
                    })
                  : 'Plan windows',
              }),
              isFetching ? jsx(GlyphSpinner, { className: 'h-3.5 w-3.5 shrink-0' }) : null,
              jsx(Tip, {
                label: 'Refresh (CLI + API, can take ~15s)',
                children: jsx(Button, {
                  size: 'sm',
                  variant: 'ghost',
                  type: 'button',
                  disabled: isFetching,
                  onClick: onRefresh,
                  children: jsxs('span', {
                    className: 'inline-flex items-center gap-1',
                    children: [
                      jsx(Codicon, { name: 'refresh', size: '0.75rem', spinning: isFetching }),
                      'Refresh',
                    ],
                  }),
                }),
              }),
            ],
          })
        : null,

      isLoading && !data
        ? jsxs('div', {
            className:
              'flex flex-1 flex-col items-center justify-center gap-2 text-(--ui-text-tertiary)',
            children: [
              jsx(GlyphSpinner, { className: 'h-5 w-5' }),
              jsx('span', {
                className: 'text-[0.75rem]',
                children: 'Reading plan windows…',
              }),
            ],
          })
        : null,

      showError
        ? jsx(ErrorState, {
            title: 'Usage unavailable',
            description: errMsg || 'Could not load plan windows.',
            action: jsx(Button, {
              size: 'sm',
              type: 'button',
              onClick: () => {
                haptic('tap')
                void refetch()
              },
              children: 'Retry',
            }),
          })
        : null,

      !isLoading && !showError && !anyWindows
        ? jsx(EmptyState, {
            title: 'No plan windows',
            description: 'No provider reported limits yet.',
          })
        : null,

      anyWindows || (providers.length > 0 && !showError && !isLoading)
        ? jsx(ScrollArea, {
            className: 'min-h-0 flex-1',
            children: jsx('div', {
              className: 'flex flex-col gap-2.5 pr-0.5',
              children: providers.map((p) =>
                jsx(ProviderSection, { provider: p }, p.id)
              ),
            }),
          })
        : null,

      jsxs('div', {
        className: cn(
          'flex items-center justify-between gap-2 pt-0.5',
          'text-[0.5625rem] text-(--ui-text-quaternary)'
        ),
        children: [
          jsx('span', {
            className: 'truncate',
            children: data?.source || 'CLI /usage',
          }),
          jsx('span', {
            className: 'shrink-0',
            children: data?.refreshed_at
              ? `${data.cached ? 'cached · ' : ''}${formatRefresh(data.refreshed_at)}`
              : '',
          }),
        ],
      }),
    ],
  })
}

function StatusChip({ rest, onToggle }) {
  const open = useValue($floatingOpen)
  const { data, isFetching, isError } = useUsage(rest)
  const providers = providersFromPayload(data)
  const worst = worstAcross(providers)
  const label = !worst
    ? isFetching
      ? 'LLM…'
      : isError
        ? 'LLM ?'
        : 'LLM'
    : worst.used_pct >= 100
      ? 'LLM maxed'
      : `LLM ${Math.round(100 - worst.used_pct)}%`

  return jsx(Tip, {
    label: open
      ? worst
        ? `${worst.provider_name} ${shortLabel(worst)} · ${Math.round(worst.used_pct)}% · click to hide`
        : 'Hide LLM usage panel'
      : 'Show LLM usage panel',
    children: jsx('button', {
      type: 'button',
      className: cn(
        'inline-flex h-full items-center gap-1 px-1.5 text-[0.6875rem] transition-colors',
        'text-(--ui-text-tertiary) hover:bg-(--chrome-action-hover) hover:text-foreground',
        open ? '' : 'opacity-80'
      ),
      onClick: () => {
        haptic('tap')
        onToggle()
      },
      children: label,
    }),
  })
}

export default {
  id: ID,
  name: 'LLM Usage',
  register(ctx) {
    // Restore last open/closed preference.
    const storedOpen = ctx.storage.get(OPEN_STORAGE_KEY, true)
    $floatingOpen.set(storedOpen !== false)

    /** @type {null | (() => void)} */
    let disposePane = null

    const setOpen = (next) => {
      $floatingOpen.set(next)
      ctx.storage.set(OPEN_STORAGE_KEY, next)
      // Registry `when` is not reactive — must re-register to show/hide.
      if (next) {
        if (!disposePane) {
          disposePane = ctx.register({
            id: 'pane',
            area: 'panes',
            title: 'LLM Usage',
            data: {
              placement: 'floating',
              anchor: 'top-right',
              width: '280px',
              height: '420px',
              headerActions: () =>
                jsx(FloatHeaderActions, {
                  rest: ctx.rest,
                  onClose: () => setOpen(false),
                }),
            },
            render: () => jsx(UsageBoard, { rest: ctx.rest, mode: 'float' }),
          })
        }
      } else if (disposePane) {
        disposePane()
        disposePane = null
      }
    }

    // Mount floating pane if last state was open.
    if ($floatingOpen.get()) {
      setOpen(true)
    }

    ctx.register({
      id: 'page',
      area: ROUTES_AREA,
      data: { path: ROUTE },
      render: () => jsx(UsageBoard, { rest: ctx.rest, mode: 'page' }),
    })

    ctx.register({
      id: 'nav',
      area: SIDEBAR_NAV_AREA,
      data: {
        path: ROUTE,
        label: 'LLM Usage',
        codicon: 'graph',
      },
    })

    ctx.register({
      id: 'chip',
      area: 'statusBar.right',
      order: 125,
      render: () =>
        jsx(StatusChip, {
          rest: ctx.rest,
          onToggle: () => setOpen(!$floatingOpen.get()),
        }),
    })

    ctx.registerMany([
      {
        id: 'open',
        area: PALETTE_AREA,
        data: {
          id: 'llm-usage.open',
          label: 'Show LLM usage panel',
          keywords: ['llm', 'claude', 'grok', 'codex', 'venice', 'usage', 'quota'],
          run: () => setOpen(true),
        },
      },
      {
        id: 'hide',
        area: PALETTE_AREA,
        data: {
          id: 'llm-usage.hide',
          label: 'Hide LLM usage panel',
          keywords: ['llm', 'usage', 'close', 'hide'],
          run: () => setOpen(false),
        },
      },
      {
        id: 'page-open',
        area: PALETTE_AREA,
        data: {
          id: 'llm-usage.page',
          label: 'Open LLM usage page',
          keywords: ['llm', 'usage', 'page'],
          run: () => {
            setOpen(true)
            host.navigate(ROUTE)
          },
        },
      },
      {
        id: 'refresh',
        area: PALETTE_AREA,
        data: {
          id: 'llm-usage.refresh',
          label: 'Refresh LLM usage',
          keywords: ['llm', 'claude', 'grok', 'codex', 'venice', 'refresh'],
          run: async () => {
            try {
              const payload = await refreshUsage(ctx.rest)
              const providers = providersFromPayload(payload)
              const worst = worstAcross(providers)
              host.notify({
                kind: worst && worst.used_pct >= 90 ? 'warning' : 'info',
                message: worst
                  ? `LLM usage refreshed · ${worst.provider_name} ${shortLabel(worst)} ${Math.round(worst.used_pct)}%`
                  : 'LLM usage refreshed',
              })
            } catch (err) {
              host.notifyError(err, 'LLM usage refresh failed')
            }
          },
        },
      },
    ])
  },
}
