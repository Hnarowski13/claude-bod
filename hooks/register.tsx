// The face of Claude Bod: the movement nudges, drawn with buttons. The brain
// is scripts/bod.py, which decides when a nudge is due and keeps the one
// on show in a state file every session shares; this module polls it, draws
// what it says, and sends the button presses back.
//
// An exercise or standing-desk nudge takes the session over: a panel with the
// nudge in giant letters, and no prompt is sent until it's done (or put off
// with "not now"). Kindness nudges and the "stop for the day" line only show
// in the band above the prompt.
//
// It also caps how many Claudes are open at once (scripts/claude-limit.py):
// a session past the cap has its prompts refused until an older one closes.
import { atom, read, update } from 'claude-code'
import type { Elements, EngineInterface, Register } from 'claude-code'

import type { Nudge, Reply, View } from '../types'
import { banner } from './banner'

const POLL_MS = 5000
const SOUND = '/System/Library/Sounds/Glass.aiff'
const ICONS = { move: '🤸', stand: '🚶', kind: '💛' }
const PANE = 'bod'
const PANE_ROWS = 16
// Frame, padding, heading, gaps and the button row around the giant letters.
const CARD_CHROME_ROWS = 9
const CARD_CHROME_COLUMNS = 6

const view = atom({ plugin: 'bod', key: 'view' } as const, null)
const now = atom({ plugin: 'bod', key: 'now' } as const, 0)

type Command = 'tick' | 'go' | 'done' | 'snooze' | 'beep'
type Press = { go: () => void; done: () => void; snooze: () => void }
// The elements a nudge is drawn with; every surface's table has them.
type Drawing = Pick<Elements['terminal'], 'Box' | 'Button' | 'Text'>

export const clock = (seconds: number) =>
  `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`

export const headline = (nudge: Nudge) => {
  if (nudge.kind === 'move') {
    return `Movement break: ${nudge.text}`
  }

  return nudge.kind === 'kind' ? `Be nice to yourself: ${nudge.text}` : nudge.text
}

// The nudges that take the session over until they're done.
export const locks = (nudge: Nudge | null | undefined): nudge is Nudge =>
  nudge !== null && nudge !== undefined && nudge.kind !== 'kind'

// Where a running timer stands: up for reps, down for a timed hold like the plank.
export const reading = (nudge: Nudge, at: number) => {
  const elapsed = Math.max(0, Math.floor((at - (nudge.started ?? at)) / 1000))

  if (nudge.seconds === null) {
    return { digits: clock(elapsed), isOver: false, text: clock(elapsed) }
  }

  const left = Math.max(0, nudge.seconds - elapsed)

  return { digits: clock(left), isOver: left === 0, text: left === 0 ? "time's up! 🎉" : `${clock(left)} left` }
}

// What the giant letters say before go is pressed.
export const shout = (nudge: Nudge) => (nudge.kind === 'stand' ? 'STAND UP' : nudge.text.replace(/^an? /, ''))

// Where bod.py is, once session.start has checked it runs; null when it doesn't.
let script: string | null = null
// The `started` of the countdown this session already asked to beep for.
let beepAsked: number | null = null

async function bod($: EngineInterface, command: Command): Promise<Reply | null> {
  if (script === null) {
    return null
  }

  try {
    const { exitCode, stdout } = await $.process.run(['python3', script, command], { timeoutMs: 10000 })

    if (exitCode !== 0) {
      return null
    }

    const { nudge, stop, ...rest } = JSON.parse(stdout) as Reply

    await show($, { nudge, stop }, rest.now)

    return { nudge, stop, ...rest }
  } catch {
    return null
  }
}

// `/bod level hard`, `/bod every 10`, `/bod level hard every 10` (or `level hard 10`), `/bod settings`: bod.py keeps the choice
// and says what Claude Bod is set to now, or what to pick from.
async function settings($: EngineInterface, args: string[]): Promise<string> {
  if (script === null) {
    return 'Claude Bod needs python3 to run.'
  }

  try {
    const { stdout } = await $.process.run(['python3', script, ...args], { timeoutMs: 10000 })

    return stdout.trim()
  } catch {
    return 'Claude Bod could not save that.'
  }
}

// Why this session may not send prompts right now, or null when it may. Too
// many Claudes open is the only reason; a broken script lets everything through.
async function overLimit($: EngineInterface): Promise<string | null> {
  try {
    const stdin = JSON.stringify({ session_id: await $.session.id() })
    const { exitCode, stdout } = await $.process.run(['python3', `${$.plugin.root}/scripts/claude-limit.py`], {
      stdin,
      timeoutMs: 5000,
    })

    if (exitCode !== 0 || stdout.trim() === '') {
      return null
    }

    const { decision, reason } = JSON.parse(stdout) as { decision?: string; reason?: string }

    return decision === 'block' && reason ? `🧠 ${reason}` : null
  } catch {
    return null
  }
}

// Draws `next`, opening or closing the takeover panel to match. Only a real
// change redraws anything, not every poll.
async function show($: EngineInterface, next: View | null, at: number) {
  const shown = await read($, view)

  if (JSON.stringify(next) === JSON.stringify(shown)) {
    return
  }

  // The panel opens before the view changes, so the band, drawn again by that
  // change, already sees it and leaves the nudge to it.
  if (locks(next?.nudge) && !locks(shown?.nudge)) {
    await $.ui.open({ id: PANE, title: 'Claude Bod', focus: true, rows: PANE_ROWS }).catch(() => undefined)
  }

  await update($, now, () => at)
  await update($, view, () => next)

  if (!locks(next?.nudge) && locks(shown?.nudge)) {
    await $.ui.close({ id: PANE }).catch(() => undefined)
  }
}

// Runs once a second: moves the timer on show, and rings at a countdown's end.
async function second($: EngineInterface) {
  const nudge = (await read($, view))?.nudge

  if (!nudge || nudge.started === null) {
    return
  }

  const at = await $.clock.now()
  await update($, now, () => at)

  const isOver = nudge.seconds !== null && at - nudge.started >= nudge.seconds * 1000

  if (isOver && beepAsked !== nudge.started) {
    beepAsked = nudge.started

    // Every session sees the countdown end; bod.py lets one of them ring.
    if ((await bod($, 'beep'))?.beep) {
      await $.process.run(['afplay', SOUND]).catch(() => undefined)
    }
  }
}

async function finish($: EngineInterface) {
  const reply = await bod($, 'done')

  if (reply !== null) {
    $.ui.toast(reply.took === undefined ? 'Nice 💛' : `Nice, ${clock(reply.took)} 💪`)
  }
}

async function isPanelDrawn($: EngineInterface) {
  const panes = await $.ui.panes().catch(() => [])

  return panes.some(pane => pane.id === PANE && pane.isPlaced)
}

// The takeover card: the nudge in giant letters (the timer, once it runs)
// over its buttons. Null when it doesn't fit in `rows`.
function card(
  { Box, Button, Text }: Drawing,
  nudge: Nudge,
  at: number,
  press: Press,
  room: { columns: number; rows: number }
) {
  const isRunning = nudge.started !== null
  const timer = reading(nudge, at)
  const letters = banner(
    isRunning ? (timer.isOver ? 'TIME!' : timer.digits) : shout(nudge),
    room.columns - CARD_CHROME_COLUMNS
  )

  if (letters.length + CARD_CHROME_ROWS > room.rows) {
    return null
  }

  return (
    <Box flexDirection="column" borderStyle="double" borderColor="claude" paddingX={2} paddingY={1} gap={1}>
      <Box gap={1} flexWrap="wrap">
        <Text bold>
          {ICONS[nudge.kind]} {isRunning && nudge.kind === 'stand' ? 'Standing / walking' : headline(nudge)}
        </Text>
        <Text dimColor>· no prompts until this is done</Text>
      </Box>
      <Box flexDirection="column">
        {letters.map(row => (
          <Text bold color={isRunning ? 'success' : 'claude'}>
            {row === '' ? ' ' : row}
          </Text>
        ))}
      </Box>
      {isRunning ? (
        <Box gap={1}>
          <Text color="success">⏱ {timer.text}</Text>
          <Button key="done" label="done ✓" hotkey="d" variant="primary" onPress={press.done} />
        </Box>
      ) : (
        <Box gap={1}>
          <Button key="go" label="go! ▶" hotkey="g" variant="primary" onPress={press.go} />
          <Button key="snooze" label="not now (5 min)" hotkey="n" onPress={press.snooze} />
        </Box>
      )}
    </Box>
  )
}

// The one-line nudge: every kindness nudge, and the others where the card
// has no room.
function line({ Box, Button, Text }: Drawing, nudge: Nudge, at: number, press: Press) {
  if (nudge.started !== null) {
    return (
      <Box key="nudge" gap={1} flexWrap="wrap">
        <Text bold>
          {ICONS[nudge.kind]} {nudge.kind === 'stand' ? 'Standing / walking' : nudge.text}
        </Text>
        <Text color="success">⏱ {reading(nudge, at).text}</Text>
        <Button key="done" label="done ✓" hotkey="d" variant="primary" onPress={press.done} />
      </Box>
    )
  }

  return (
    <Box key="nudge" gap={1} flexWrap="wrap">
      <Text bold>
        {ICONS[nudge.kind]} {headline(nudge)}
      </Text>
      {nudge.kind === 'kind' ? (
        <Button key="done" label="done ✓" hotkey="d" variant="primary" onPress={press.done} />
      ) : (
        <Button key="go" label="go! ▶" hotkey="g" variant="primary" onPress={press.go} />
      )}
      <Button key="snooze" label="not now" hotkey="n" onPress={press.snooze} />
    </Box>
  )
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    const started = await next(e)

    script = `${$.plugin.root}/scripts/bod.py`

    // bod.py doesn't run (no python3?): stay out of the way.
    if ((await bod($, 'tick')) === null) {
      script = null

      return started
    }

    // Asked for by name, the panel is placed on a terminal of any width; opened
    // by the mod alone it only shows on a wide one.
    await $.command.register({
      name: 'bod',
      description: 'Open the Claude Bod panel, or set the level and how often to exercise',
      argumentHint: '[level easy|medium|hard] [[every] 5|10|15]',
    })

    $.clock.every(POLL_MS, () => void bod($, 'tick'))
    $.clock.every(1000, () => void second($).catch(() => undefined))

    return started
  })

  on('command.run', { command: 'bod' }, async ($, e) => {
    const args = (e.args ?? '').trim().split(/\s+/).filter(Boolean)
    const [setting] = args

    if (setting === 'level' || setting === 'every') {
      return { text: await settings($, args) }
    }

    if (setting === 'settings') {
      return { text: await settings($, ['settings']) }
    }

    await $.ui.open({ id: PANE, title: 'Claude Bod', focus: true, rows: PANE_ROWS })

    return { text: 'Claude Bod panel opened.' }
  })

  // The lock: while an exercise or standing-desk nudge is on show, nothing she
  // types is sent. A broken bod.py never locks her out: the nudge is taken
  // down and the prompt goes through, as it does when this hook fails.
  on('prompt.submit', async ($, e, next) => {
    if (e.origin.kind !== 'composer' && e.origin.kind !== 'bridge') {
      return next(e)
    }

    const over = await overLimit($)

    if (over !== null) {
      await $.prompt.fill({ text: e.text }).catch(() => undefined)

      return { drop: over }
    }

    if (script === null) {
      return next(e)
    }

    // Counts toward today's hours and the nudge timers.
    await $.process.run(['python3', script, 'hook'], { timeoutMs: 10000 }).catch(() => undefined)

    const reply = await bod($, 'tick')

    if (reply === null) {
      await show($, null, await $.clock.now())

      return next(e)
    }

    if (!locks(reply.nudge)) {
      return next(e)
    }

    // Her words go back in the box, to send once she's done.
    await $.prompt.fill({ text: e.text }).catch(() => undefined)

    return {
      drop: `${ICONS[reply.nudge.kind]} ${headline(reply.nudge)} first! Press go and then done, or "not now" for 5 minutes (click a button, or ctrl+x tab for the keys).`,
    }
  })

  // Her close mark doesn't get her out of it; "not now" does.
  on('ui.close', { id: PANE }, async ($, e, next) => {
    if (e.origin.kind === 'person' && locks((await read($, view))?.nudge)) {
      return { value: undefined }
    }

    return next(e)
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const elements = $.ui.resolve(e)
    const { Box, Text } = elements
    const nudge = (await read($, view))?.nudge

    if (!locks(nudge)) {
      return (
        <Box>
          <Text dimColor>Nothing to do right now 💛 The next nudge will show up here.</Text>
        </Box>
      )
    }

    const at = await read($, now)
    const press: Press = { go: () => void bod($, 'go'), done: () => void finish($), snooze: () => void bod($, 'snooze') }
    const room = { columns: e.props.bodyColumns, rows: e.viewport?.rows ?? 24 }

    return card(elements, nudge, at, press, room) ?? line(elements, nudge, at, press)
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    const shown = await read($, view)

    if (e.props.hasSurvey || shown === null || (shown.nudge === null && shown.stop === null)) {
      return next(e)
    }

    const elements = $.ui.resolve(e)
    const { Box, Text } = elements
    const { nudge, stop } = shown
    // Read up here so a running timer draws the band again every second, which
    // is also when it notices the panel has gone and takes the nudge back.
    const at = await read($, now)
    const rows = []

    if (stop !== null) {
      rows.push(<Text color="warning">🛑 {stop}</Text>)
    }

    // A nudge that locks belongs to the panel; it is drawn here, as large as
    // the band allows, only when no panel is on screen.
    if (nudge !== null && !(locks(nudge) && (await isPanelDrawn($)))) {
      const press: Press = { go: () => void bod($, 'go'), done: () => void finish($), snooze: () => void bod($, 'snooze') }
      const room = { columns: e.props.bodyColumns, rows: e.props.maxRows - rows.length }

      rows.push((locks(nudge) ? card(elements, nudge, at, press, room) : null) ?? line(elements, nudge, at, press))
    }

    if (rows.length === 0) {
      return next(e)
    }

    return <Box flexDirection="column">{rows}</Box>
  })
}
