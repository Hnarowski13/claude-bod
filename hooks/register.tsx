// The face of Claude Bod: the movement nudges, drawn with buttons. The brain
// is scripts/bod.py, which decides when a nudge is due and keeps the one
// on show in a state file every session shares; this module polls it, draws
// what it says, and sends the button presses back.
//
// An exercise nudge takes the session over: a box in the
// band above the prompt, full width, and no prompt is sent until it's done (or
// put off with "not now"). So does the workflow check-in every 45 minutes,
// with one thing to try against Claude-FOG. Kindness nudges and the "stop for the day" line
// show in the same band as a single line.
//
// The status line under the prompt keeps a running total of today's hours,
// beside the countdowns to the next nudges and how many she's skipped today.
//
// It also caps how many Claudes are open at once (scripts/claude-limit.py):
// a session past the cap has its prompts refused until an older one closes.
import { atom, read, update } from 'claude-code'
import type { Elements, EngineInterface, Register } from 'claude-code'

import type { Nudge, Reply, View } from '../types'

const POLL_MS = 5000
const SOUND = '/System/Library/Sounds/Glass.aiff'
const ICONS = { move: '🤸', kind: '💛', check: '🧭' }
const TITLES = { move: 'Movement break', check: 'Workflow check-in' }
// What the check-in asks, over the one thing to try (bod.py's CHECK_IN_QUESTION).
const CHECK_IN_QUESTION = "How's the workflow going? Feeling the Claude-FOG?"
// The box's frame, its heading, the blank rows and the button row around the lines.
const CARD_CHROME_ROWS = 6

const view = atom({ plugin: 'bod', key: 'view' } as const, null)
const now = atom({ plugin: 'bod', key: 'now' } as const, 0)

type Command = 'tick' | 'now' | 'kindnow' | 'go' | 'done' | 'snooze' | 'beep'
type Press = { go: () => void; done: () => void; snooze: () => void }
// The elements a nudge is drawn with; every surface's table has them.
type Drawing = Pick<Elements['terminal'], 'Box' | 'Button' | 'Text'>

export const clock = (seconds: number) =>
  `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`

// The exercises in a set, in order: bod.py joins them with ", then ".
export const steps = (nudge: Nudge) => nudge.text.split(', then ')

// A set on one line, an arrow between exercises.
const inLine = (nudge: Nudge) => steps(nudge).join(' → ')

export const headline = (nudge: Nudge) => {
  if (nudge.kind === 'move') {
    return `Movement break: ${inLine(nudge)}`
  }

  if (nudge.kind === 'check') {
    return `Workflow check-in: ${CHECK_IN_QUESTION} Try this: ${nudge.text}`
  }

  return nudge.kind === 'kind' ? `Be nice to yourself: ${nudge.text}` : nudge.text
}

// Said on a nudge that comes back after "not now": once already, twice, 3 times.
export const skippedNote = (nudge: Nudge) => {
  const skipped = nudge.skipped ?? 0

  if (skipped === 0) {
    return null
  }

  return `you skipped ${skipped === 1 ? 'once' : skipped === 2 ? 'twice' : `${skipped} times`} already`
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

// Time worked today the way bod.py's /work-check says it: 14m, 2h 05m.
export const hours = (seconds: number) => {
  const minutes = Math.floor(seconds / 60)

  return minutes >= 60 ? `${Math.floor(minutes / 60)}h ${String(minutes % 60).padStart(2, '0')}m` : `${minutes}m`
}

// The status line: how long she's worked today, then how long until the next
// exercise nudge (left out while one is on show), then how many nudges she's
// put off with "not now" today. Rounded up, so 0:00 is the moment it's due.
export const countdown = (shown: View | null, at: number) => {
  const worked = typeof shown?.worked === 'number' ? `⏱ ${hours(shown.worked)} today` : null
  const parts: string[] = []

  if (shown?.paused) {
    parts.push('⏸ Claude Bod is paused until your next prompt')
  } else if (shown?.next) {
    const { move } = shown.next

    if (move !== undefined) {
      parts.push(`${ICONS.move} move in ${clock(Math.max(0, Math.ceil((move - at) / 1000)))}`)
    }
  }

  if (shown?.skips) {
    parts.push(`🙈 ${shown.skips} skipped today`)
  }

  const line = [worked, ...parts].filter(part => part !== null)

  return line.length > 0 ? line.join(' · ') : undefined
}

// Where bod.py is, once session.start has checked it runs; null when it doesn't.
let script: string | null = null
// The `started` of the countdown this session already asked to beep for.
let beepAsked: number | null = null
// What the status line says now, so it's only set when that changes.
let status: string | undefined
// The due time this session already polled for, so a nudge shows the second
// its countdown ends instead of on the next 5 second poll.
let dueAsked: number | null = null

async function bod($: EngineInterface, command: Command): Promise<Reply | null> {
  if (script === null) {
    return null
  }

  try {
    const { exitCode, stdout } = await $.process.run(['python3', script, command], { timeoutMs: 10000 })

    if (exitCode !== 0) {
      return null
    }

    const { nudge, stop, next = null, paused = false, worked = null, skips = 0, ...rest } = JSON.parse(stdout) as Reply

    await show($, { nudge, stop, next, paused, worked, skips }, rest.now)

    return { nudge, stop, next, paused, worked, skips, ...rest }
  } catch {
    return null
  }
}

// `/bod level hard`, `/bod every 10`, `/bod kind 30`, `/bod claudes 5`, `/bod level hard every 10` (or `level hard 10`), `/bod settings`, `/bod info`: bod.py keeps the choice
// and says what changed (`settings` sums it up, `info` lists every setting), or what to pick from.
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

// Draws `next`. Only a real change redraws anything, not every poll.
async function show($: EngineInterface, next: View | null, at: number) {
  const shown = await read($, view)

  if (JSON.stringify(next) === JSON.stringify(shown)) {
    return
  }

  await update($, now, () => at)
  await update($, view, () => next)
}

// Runs once a second: moves the countdown in the status line and the timer on
// show, and rings at a timer's end.
async function second($: EngineInterface) {
  let shown = await read($, view)
  const at = await $.clock.now()
  const due = Math.min(...Object.values(shown?.next ?? {}))

  if (due <= at && dueAsked !== due) {
    dueAsked = due
    await bod($, 'tick')
    shown = await read($, view)
  }

  const text = countdown(shown, at)

  if (text !== status) {
    status = text
    $.ui.status(text)
  }

  const nudge = shown?.nudge

  if (!nudge || nudge.started === null) {
    return
  }

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

    // And a line in the chat, under the nudge's own.
    $.ui.log(reply.took === undefined ? '✅ Nice job!' : `✅ Nice job! ${clock(reply.took)}`)
  }
}

// The takeover card: a box with what to do, one exercise per line, over the
// timer and buttons; for a check-in, the question and the one thing to try.
// Null when it doesn't fit in `rows`.
function card({ Box, Button, Text }: Drawing, nudge: Nudge, at: number, press: Press, rows: number) {
  const isRunning = nudge.started !== null
  const timer = reading(nudge, at)
  const isCheck = nudge.kind === 'check'
  const todo = isCheck ? [CHECK_IN_QUESTION, `Try this: ${nudge.text}`] : steps(nudge)
  const note = skippedNote(nudge)

  if (todo.length + CARD_CHROME_ROWS > rows) {
    return null
  }

  return (
    <Box key="nudge" flexDirection="column" borderStyle="round" borderColor="claude" paddingX={1} gap={1}>
      <Box gap={1} flexWrap="wrap">
        <Text bold color="claude">
          {ICONS[nudge.kind]} {isCheck ? TITLES.check : TITLES.move}
        </Text>
        <Text dimColor>· no prompts until this is done</Text>
        {note !== null ? <Text color="warning">· {note}</Text> : null}
      </Box>
      <Box flexDirection="column" paddingX={2}>
        {todo.map((step, index) => (
          <Text bold>{todo.length > 1 && !isCheck ? `${index + 1}. ${step}` : step}</Text>
        ))}
      </Box>
      {isCheck ? (
        <Box gap={1}>
          <Button key="done" label="done ✓" hotkey="d" variant="primary" onPress={press.done} />
          <Button key="snooze" label="not now (5 min)" hotkey="n" onPress={press.snooze} />
        </Box>
      ) : isRunning ? (
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
  const note = skippedNote(nudge)

  if (nudge.started !== null) {
    return (
      <Box key="nudge" gap={1} flexWrap="wrap">
        <Text bold>
          {ICONS[nudge.kind]} {inLine(nudge)}
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
      {note !== null ? <Text color="warning">({note})</Text> : null}
      {nudge.kind !== 'move' ? (
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

    await $.command.register({
      name: 'bod',
      description: 'Exercise or be kind right now, or set the level, how often to exercise or be kind, and how many Claudes may be open',
      argumentHint: '[info] [now] [kind now] [level easy|medium|hard] [[every] 5|10|15] [kind 5|10|15|30|45] [claudes 1-20]',
    })

    $.clock.every(POLL_MS, () => void bod($, 'tick'))
    $.clock.every(1000, () => void second($).catch(() => undefined))

    return started
  })

  on('command.run', { command: 'bod' }, async ($, e) => {
    const args = (e.args ?? '').trim().split(/\s+/).filter(Boolean)
    const [setting] = args
    const kindNow = setting === 'kind' && args[1] === 'now'

    if (!kindNow && (setting === 'level' || setting === 'every' || setting === 'kind' || setting === 'claudes' || setting === 'info')) {
      return { text: await settings($, args) }
    }

    const reply = kindNow ? await bod($, 'kindnow') : setting === 'now' ? await bod($, 'now') : null

    if (reply?.nudge) {
      return { text: `${ICONS[reply.nudge.kind]} ${headline(reply.nudge)}` }
    }

    // `/bod` alone or `/bod settings`: what it's set to, and how to start now.
    return { text: `${await settings($, ['settings'])} /bod now for an exercise right away.` }
  })

  // The lock: while an exercise nudge is on show, nothing she
  // types is sent. A broken bod.py never locks her out: the nudge is taken
  // down and the prompt goes through, as it does when this hook fails.
  on('prompt.submit', async ($, e, next) => {
    if (e.origin.kind !== 'composer' && e.origin.kind !== 'bridge') {
      return next(e)
    }

    const over = await overLimit($)

    // Claude Code puts a dropped prompt back in the box itself; filling it
    // here as well showed her words twice.
    if (over !== null) {
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

    const how = reply.nudge.kind === 'move' ? 'Press go and then done' : 'Press done'

    return {
      drop: `${ICONS[reply.nudge.kind]} ${headline(reply.nudge)} first! ${how}, or "not now" for 5 minutes (click a button, or ctrl+x tab for the keys).`,
    }
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    const shown = await read($, view)

    if (e.props.hasSurvey || shown === null || (shown.nudge === null && shown.stop === null)) {
      return next(e)
    }

    const elements = $.ui.resolve(e)
    const { Box, Text } = elements
    const { nudge, stop } = shown
    // Read up here so a running timer draws the band again every second.
    const at = await read($, now)
    const rows = []

    if (stop !== null) {
      rows.push(<Text color="warning">🛑 {stop}</Text>)
    }

    // A nudge that locks gets the box when the band has the rows for it.
    if (nudge !== null) {
      const press: Press = { go: () => void bod($, 'go'), done: () => void finish($), snooze: () => void bod($, 'snooze') }
      const room = e.props.maxRows - rows.length

      rows.push((locks(nudge) ? card(elements, nudge, at, press, room) : null) ?? line(elements, nudge, at, press))
    }

    if (rows.length === 0) {
      return next(e)
    }

    return <Box flexDirection="column">{rows}</Box>
  })
}
