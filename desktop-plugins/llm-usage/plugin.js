/**
 * LLM Usage — Hermes Desktop plugin
 *
 * Floating HUD (close via in-panel ✕; reopen from status-bar chip):
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
  Tip,
  atom,
  cn,
  haptic,
  host,
  queryClient,
  useQuery,
  useValue,
} from '@hermes/plugin-sdk'
import { jsx, jsxs } from 'react/jsx-runtime'

const ID = 'llm-usage'
const ROUTE = '/llm-usage'
const REST_TIMEOUT_MS = 90_000
// v2 intentionally opens once after removing the nonstandard shell-header
// dependency. Later close/reopen choices persist normally under this key.
const OPEN_STORAGE_KEY = 'floatingOpen.v2'
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

/**
 * Palette — quiet until it matters.
 *
 * A quota with headroom needs no attention, so it stays near-monochrome; only
 * rows approaching their ceiling take colour, ramping amber → ember → crimson
 * so the panel reads like a gauge running hot. Literal hex on purpose: the
 * theme defines no `--ui-warning` / `--ui-danger`, so anything keyed to those
 * silently collapses to `--ui-accent` and every row looks identical.
 *
 * Length is the primary encoding and colour is secondary, so the gauge still
 * reads without hue. Maxed additionally swaps to a hatch.
 */
const WATCH_AT = 60
const RISK_AT = 85
const TONES = {
  calm: { fill: 'color-mix(in srgb, var(--ui-text-primary) 62%, transparent)', text: null },
  watch: { fill: '#d99a2b', text: '#d99a2b' },
  risk: { fill: '#e2673c', text: '#e2673c' },
  maxed: { fill: '#d94853', text: '#d94853' },
}
// Kept well below the calm fill so a low reading still reads as filled.
const BAR_TRACK = 'color-mix(in srgb, var(--ui-text-primary) 12%, transparent)'

function toneFor(used) {
  if (used >= 100) return TONES.maxed
  if (used >= RISK_AT) return TONES.risk
  if (used >= WATCH_AT) return TONES.watch
  return TONES.calm
}

function prefersReducedMotion() {
  try {
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches
  } catch {
    return false
  }
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

const MONTHS = { jan: 0, feb: 1, mar: 2, apr: 3, may: 4, jun: 5, jul: 6, aug: 7, sep: 8, oct: 9, nov: 10, dec: 11 }
const WEEKDAYS = { sun: 0, mon: 1, tue: 2, wed: 3, thu: 4, fri: 5, sat: 6 }

/** Venice puts a balance in the reset slot — don't caption money as a time. */
function looksLikeMoney(text) {
  return /^\$|\b(USD|DIEM)\b/i.test(text)
}

/**
 * Fallback parse of a provider's raw reset wording, mirroring
 * `parse_reset_to_epoch()` in plugin_api.py.
 *
 * The backend normally supplies `resets_at`, but a dashboard that hasn't been
 * restarted serves payloads without it — and formatting must not depend on
 * backend deploy state, or the rows silently revert to three different formats.
 */
function parseResetLabel(text, now = new Date()) {
  if (!text) return null
  let low = String(text)
    .replace(/\s*\([^)]*\)\s*$/, '')
    .replace(/\s+[A-Z]{2,5}$/, '')
    .trim()
    .toLowerCase()
    .replace(/,/g, ' ')

  let month = null
  let day = null
  let m = low.match(/\b([a-z]{3})[a-z]*\.?\s+(\d{1,2})\b/)
  if (m && m[1] in MONTHS) {
    month = MONTHS[m[1]]
    day = parseInt(m[2], 10)
  } else {
    m = low.match(/\b(\d{1,2})\s+([a-z]{3})[a-z]*\b/)
    if (m && m[2] in MONTHS) {
      month = MONTHS[m[2]]
      day = parseInt(m[1], 10)
    }
  }
  if (m && month !== null) {
    low = `${low.slice(0, m.index)} ${low.slice(m.index + m[0].length)}`.trim()
  }

  let weekday = null
  if (month === null) {
    const wd = low.match(/\b([a-z]{3})[a-z]*\b/)
    if (wd && wd[1] in WEEKDAYS) weekday = WEEKDAYS[wd[1]]
  }

  let hour = 0
  let minute = 0
  let haveTime = false
  let t = low.match(/\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b/)
  if (t) {
    hour = parseInt(t[1], 10) % 12
    minute = t[2] ? parseInt(t[2], 10) : 0
    if (t[3] === 'pm') hour += 12
    haveTime = true
  } else {
    t = low.match(/\b(\d{1,2}):(\d{2})\b/)
    if (t) {
      hour = parseInt(t[1], 10)
      minute = parseInt(t[2], 10)
      haveTime = true
    }
  }
  if (hour > 23 || minute > 59) return null
  if (month === null && weekday === null && !haveTime) return null

  const target = new Date(now.getTime())
  target.setSeconds(0, 0)
  target.setHours(hour, minute)
  if (month !== null && day !== null) {
    target.setMonth(month, day)
    // No year in the text — roll forward when it already passed.
    if (target.getTime() < now.getTime() - 86_400_000) {
      target.setFullYear(target.getFullYear() + 1)
    }
  } else if (weekday !== null) {
    let ahead = (weekday - target.getDay() + 7) % 7
    if (ahead === 0 && target.getTime() < now.getTime()) ahead = 7
    target.setDate(target.getDate() + ahead)
  } else if (target.getTime() < now.getTime()) {
    target.setDate(target.getDate() + 1)
  }
  return target.getTime() / 1000
}

function resolveResetEpoch(window_) {
  const at = window_.resets_at
  if (typeof at === 'number' && isFinite(at)) return at
  const raw = formatReset(window_.reset_label)
  if (!raw || looksLikeMoney(raw)) return null
  return parseResetLabel(raw)
}

/**
 * One format for every provider: weekday, date, then time — "Fri 31 Jul, 9:59 am".
 *
 * The providers each state it their own way ("1:30pm", "Jul 31 at 10am",
 * "August 3, 07:22", "Aug 5 at 2:09 PM AEST") and all of them print identically
 * here. Minutes are always two digits so the column aligns.
 *
 * The weekday and month come from fixed tables rather than `month: 'short'`,
 * which is not actually uniform: this locale renders July as "July" but August
 * as "Aug", so the rows would disagree with each other again. The time still
 * goes through toLocaleTimeString so it follows the 12/24-hour preference.
 * Showing the date unconditionally also leaves no near/far threshold to drift.
 */
const DAY_ABBR = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
const MONTH_ABBR = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

function formatWhen(window_) {
  const at = resolveResetEpoch(window_)
  if (at == null) return formatReset(window_.reset_label)
  try {
    const when = new Date(at * 1000)
    const date = `${DAY_ABBR[when.getDay()]} ${when.getDate()} ${MONTH_ABBR[when.getMonth()]}`
    const time = when.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
    return `${date}, ${time}`
  } catch {
    return formatReset(window_.reset_label)
  }
}

function resetTooltip(window_) {
  const raw = formatReset(window_.reset_label)
  const at = resolveResetEpoch(window_)
  // `detail` carries the underlying figures behind a percentage, e.g. Venice's
  // "$0.01 of $10.00" — too long for the row, useful on hover.
  const detail = window_.detail ? String(window_.detail) : ''
  const withDetail = (text) => (detail ? `${detail} · ${text}` : text)

  if (at == null) {
    if (!raw) return detail || 'No reset time reported'
    return looksLikeMoney(raw) ? raw : withDetail(`Resets ${raw}`)
  }
  const ms = at * 1000 - Date.now()
  if (ms <= 0) return withDetail('Resetting now')
  const mins = Math.floor(ms / 60_000)
  const rel =
    mins < 60
      ? `${Math.max(1, mins)}m`
      : mins < 48 * 60
        ? `${Math.floor(mins / 60)}h`
        : `${Math.floor(mins / (60 * 24))}d`
  return withDetail(`Resets in ${rel}`)
}

function fetchUsage(rest, force = false) {
  return rest(force ? '/usage?force=true' : '/usage', { timeoutMs: REST_TIMEOUT_MS })
}

async function refreshUsage(rest) {
  const payload = await fetchUsage(rest, true)
  queryClient.setQueryData(QUERY_KEY, payload)
  return payload
}

/** Continuous usage line. Colour carries state; the row text carries the rest. */
const BAR_HEIGHT = '4px'

function UsageBar({ used, ariaLabel }) {
  const pct = Math.max(0, Math.min(100, used))
  const tone = toneFor(pct)

  return jsx('div', {
    role: 'meter',
    'aria-valuemin': 0,
    'aria-valuemax': 100,
    'aria-valuenow': Math.round(pct),
    'aria-label': ariaLabel,
    style: {
      width: '100%',
      height: BAR_HEIGHT,
      borderRadius: '999px',
      background: BAR_TRACK,
      overflow: 'hidden',
    },
    children: jsx('div', {
      style: {
        width: `${pct}%`,
        height: '100%',
        borderRadius: '999px',
        background: tone.fill,
        transition: prefersReducedMotion() ? 'none' : 'width 320ms ease-out',
      },
    }),
  })
}

function WindowRow({ window: w }) {
  const used = w.used_pct ?? 0
  const isBalance = w.id === 'usd_balance' || w.id === 'diem_balance'
  const tone = toneFor(used)
  const label = shortLabel(w)
  const context = isBalance ? '' : formatWhen(w)
  const value = isBalance
    ? formatReset(w.reset_label).replace(/\s*remaining$/i, '') || '—'
    : used >= 100
      ? 'Maxed'
      : // Don't round a live-but-tiny reading down to a flat "0%".
        used > 0 && Math.round(used) === 0
        ? '<1%'
        : `${Math.round(used)}%`
  // A balance isn't "used", and "Maxed used" doesn't parse as English.
  const showsUsed = !isBalance && used < 100

  return jsxs('div', {
    className: 'flex flex-col gap-1 py-1',
    children: [
      jsxs('div', {
        className: 'flex items-baseline gap-1.5',
        children: [
          jsx('span', {
            className: 'min-w-0 flex-1 truncate text-[0.75rem]',
            style: {
              fontWeight: used >= WATCH_AT ? 500 : 450,
              color:
                used >= WATCH_AT
                  ? 'var(--ui-text-primary)'
                  : 'color-mix(in srgb, var(--ui-text-primary) 76%, transparent)',
            },
            children: label,
          }),
          context
            ? jsx(Tip, {
                label: resetTooltip(w),
                children: jsx('span', {
                  className: 'shrink-0 text-[0.625rem] tabular-nums text-(--ui-text-quaternary)',
                  children: context,
                }),
              })
            : null,
          jsxs('span', {
            className: 'shrink-0 text-[0.75rem] font-semibold tabular-nums',
            style: { color: tone.text || 'var(--ui-text-primary)' },
            children: [
              value,
              // "used" stays quiet so the number still leads the row.
              showsUsed
                ? jsx('span', {
                    className: 'text-[0.625rem] text-(--ui-text-quaternary)',
                    style: { fontWeight: 400 },
                    children: ' used',
                  })
                : null,
            ],
          }),
        ],
      }),
      isBalance
        ? null
        : jsx(UsageBar, {
            used,
            ariaLabel: `${label}: ${Math.round(used)} percent used. ${resetTooltip(w)}`,
          }),
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
            // Smaller and more widely tracked than the rows it labels, so
            // headers recede and the quota rows carry the panel.
            className:
              'text-[0.5625rem] font-semibold uppercase tracking-[0.14em] text-(--ui-text-quaternary)',
            children: provider.name,
          }),
          // No "unavailable" chip here — at this size it reads as a second
          // header, and the line below already says what happened.
        ],
      }),
      hasData
        ? jsx('div', {
            className: 'flex flex-col',
            children: windows.map((w) =>
              jsx(WindowRow, { window: w }, `${provider.id}:${w.id || w.label}`)
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
      // Balances aren't depletion windows — they'd read as 0% and win "worst".
      if (w.id === 'usd_balance' || w.id === 'diem_balance') continue
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
    // Poll every minute against a backend that re-reads the providers every two
    // (see _CACHE_TTL_SEC), so the panel picks up a new snapshot promptly while
    // in-between polls are cheap cache hits.
    refetchInterval: 60_000,
    // Without this React Query stops polling as soon as the window loses focus
    // — exactly when a always-on HUD most needs to stay current.
    refetchIntervalInBackground: true,
    staleTime: 30_000,
    retry: 1,
  })
}

const panelBtnClass =
  'grid size-5 place-items-center rounded text-(--ui-text-quaternary) transition-colors hover:bg-(--chrome-action-hover) hover:text-(--ui-text-primary) disabled:opacity-50'

function UsageBoard({ rest, mode, onClose }) {
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
      // Controls live inside the plugin so the floating card works on stock
      // Hermes; no core-only `headerActions` extension is required.
      jsxs('div', {
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
            children: isFloat
              ? jsx('button', {
                  type: 'button',
                  className: panelBtnClass,
                  'aria-label': 'Refresh LLM usage',
                  disabled: isFetching,
                  onClick: onRefresh,
                  children: jsx(Codicon, {
                    name: 'refresh',
                    size: '0.75rem',
                    spinning: isFetching,
                  }),
                })
              : jsx(Button, {
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
          isFloat && onClose
            ? jsx(Tip, {
                label: 'Close panel (reopen from status bar)',
                children: jsx('button', {
                  type: 'button',
                  className: panelBtnClass,
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
      }),

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

      // Footer carries freshness only. It used to echo "Claude · Grok · Codex ·
      // Venice", which is already on screen as the section headers.
      jsxs('div', {
        className: cn(
          'flex items-center justify-between gap-2 pt-0.5',
          'text-[0.5625rem] text-(--ui-text-quaternary)'
        ),
        children: [
          jsx('span', {
            className: 'truncate',
            children: data?.stale ? 'showing last good read' : '',
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
  // Chip speaks in used %, same as the panel — it previously showed remaining,
  // so the same quota read "LLM 11%" here and "89%" one click away.
  const label = !worst
    ? isFetching
      ? 'LLM…'
      : isError
        ? 'LLM ?'
        : 'LLM'
    : worst.used_pct >= 100
      ? 'LLM maxed'
      : `LLM ${Math.round(worst.used_pct)}%`
  const chipTone = worst ? toneFor(worst.used_pct) : TONES.calm

  return jsx(Tip, {
    label: open
      ? worst
        ? `${worst.provider_name} ${shortLabel(worst)} · ${Math.round(worst.used_pct)}% used · click to hide`
        : 'Hide LLM usage panel'
      : 'Show LLM usage panel',
    children: jsx('button', {
      type: 'button',
      className: cn(
        'inline-flex h-full items-center gap-1 px-1.5 text-[0.6875rem] transition-colors',
        'text-(--ui-text-tertiary) hover:bg-(--chrome-action-hover) hover:text-foreground',
        open ? '' : 'opacity-80'
      ),
      style: { color: chipTone.text || undefined },
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
            // Versioned once to discard stale off-screen geometry saved for
            // `llm-usage:pane` by an older, wider Hermes window.
            id: 'pane-v2',
            area: 'panes',
            title: 'LLM Usage',
            data: {
              placement: 'floating',
              anchor: 'top-right',
              width: '330px',
              // Fits the usual seven rows (3 Claude · Grok · Codex · 2 Venice)
              // without scrolling or a band of dead space. Still resizable, and
              // scrolls if Codex also reports its 5-hour window.
              height: '384px',
            },
            render: () =>
              jsx(UsageBoard, { rest: ctx.rest, mode: 'float', onClose: () => setOpen(false) }),
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
