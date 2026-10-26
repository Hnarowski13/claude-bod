import { expect, mock, test } from 'claude-code/testing'
import type { On } from 'claude-code'

import type { Nudge } from '../types'

const BAND = {
  plugin: 'bod',
  component: 'AbovePrompt',
  props: {
    hasSurvey: false,
    isWorking: false,
    maxRows: 6,
    bodyColumns: 100,
    scroll: { offset: 0, bodyRows: 6 },
    view: {},
  },
} as const
const PROMPT = { text: 'fix the bug', wait: false, origin: { kind: 'composer' } } as const
const START = 1_000_000
// `/bod <args>` as she'd type it.
const BOD = (args: string) =>
  ({ command: 'bod', args, origin: { kind: 'composer' }, presentation: { isFullscreen: false, columns: 100 } }) as const
const SESSION = { cwd: '/repo', surface: 'terminal', isInteractive: true } as const

// Stands in for bod.py: holds the nudge on show and answers each command as
// the script would, with the mocked clock as its time.
const fakeBod = (on: On, clock: { now: () => number }, first: Omit<Nudge, 'started'> | null) => {
  const world = {
    nudge: first === null ? null : ({ ...first, started: null } as Nudge),
    commands: [] as string[],
    toasts: [] as string[],
    sounds: 0,
    hasBeeped: false,
    // Wide enough for the engine to place a panel the mod opens on its own.
    isWide: false,
    isPanelOpen: false,
    // Every pane the mod asked the engine to open, as it asked.
    opens: [] as unknown[],
    isBroken: false,
    // claude-limit.py: what it prints, '' when this session is within the cap.
    limit: '',
    refilled: [] as string[],
    // The lines the mod added to the chat.
    logs: [] as string[],
    // When the move nudge is due, as bod.py would send it.
    next: null as { move?: number } | null,
    paused: false,
    // Seconds worked today, as bod.py would count them; undefined leaves it out.
    worked: undefined as number | undefined,
    // How many times she's said "not now" today, as bod.py would count them.
    skips: 0,
    // What the status line says, as the engine would draw it.
    status: undefined as string | undefined,
    // A nudge bod.py puts on show once the clock reaches `at`.
    due: null as { at: number; nudge: Nudge } | null,
  }

  on('session.start', () => ({ cwd: '/repo' }))
  // What the engine draws when the mod has nothing to show: an empty band.
  on('ui.render', ($, e) => {
    const { Box } = $.ui.resolve(e)

    return <Box />
  })
  on('command.register', (_$, e) => ({ value: { command: e.name } }))
  on('session.id', () => ({ value: 'session-1' }))
  on('prompt.submit', (_$, e) => ({ text: e.text }))
  on('prompt.fill', (_$, e) => {
    world.refilled.push(e.text)

    return { isFilled: true }
  })
  on('ui.open', (_$, e) => {
    world.isPanelOpen = true
    world.opens.push(e)

    return { value: world.isWide ? { isPlaced: true } : { isPlaced: false, reason: 'narrow' } }
  })
  on('ui.close', () => {
    world.isPanelOpen = false

    return { value: undefined }
  })
  on('ui.panes', () => ({
    value: world.isPanelOpen
      ? [{ id: 'bod', title: 'Claude Bod', isShown: true, isFocused: true, isPlaced: world.isWide }]
      : [],
  }))
  on('ui.status', (_$, e) => {
    world.status = e.text

    return { value: undefined }
  })
  on('ui.log', (_$, e) => {
    world.logs.push(e.text)

    return { value: undefined }
  })
  on('ui.toast', (_$, e) => {
    world.toasts.push(e.text)

    return { value: undefined }
  })
  on('process.run', (_$, e) => {
    const [program, script, command] = e.argv
    const ok = (stdout: string) => ({
      value: { exitCode: 0, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false },
    })

    if (program === 'git') {
      return ok('/repo\n')
    }

    if (program === 'afplay') {
      world.sounds += 1

      return ok('')
    }

    if (script?.endsWith('claude-limit.py')) {
      return world.isBroken ? { value: { exitCode: 1, stdout: '', stderr: 'boom', isStdoutTruncated: false, isStderrTruncated: false } } : ok(world.limit)
    }

    if (command === 'settings') {
      return ok('Claude Bod is on easy.\n')
    }

    if (command === 'choices') {
      return ok(JSON.stringify({
        settings: { level: 'easy', move: 'on', every: 5, kindness: 'on', kind: 15, check: 'on', claudes: 5, snooze: 5 },
        choices: { level: ['gentle', 'easy', 'medium', 'hard'], move: ['on', 'off'], every: [5, 10, 15], kindness: ['on', 'off'], kind: [5, 10, 15, 30, 45], check: ['on', 'off'], claudes: Array.from({ length: 10 }, (_, i) => i + 1), snooze: [2, 5, 10, 15] },
      }))
    }

    if (command === 'info') {
      return ok('Claude Bod settings:\n- Claude cap: 5\n')
    }

    if (command === 'level' || command === 'every' || command === 'kind' || command === 'move' || command === 'check' || command === 'claudes' || (command === 'snooze' && e.argv.length > 3)) {
      world.commands.push(e.argv.slice(2).join(' '))

      return ok(`Claude Bod is on ${e.argv.slice(3).join(' ')}.\n`)
    }

    if (world.isBroken) {
      return { value: { exitCode: 1, stdout: '', stderr: 'boom', isStdoutTruncated: false, isStderrTruncated: false } }
    }

    world.commands.push(command ?? '')

    if (world.due && clock.now() >= world.due.at) {
      world.nudge = world.due.nudge
      world.next = null
      world.due = null
    }

    const said: { took?: number; beep?: boolean } = {}
    const { nudge } = world

    if (command === 'swap' && nudge && nudge.kind === 'move' && nudge.started === null) {
      world.nudge = { ...nudge, text: '10 calf raises' }
    } else if (command === 'go' && nudge) {
      world.nudge = { ...nudge, started: clock.now() }
    } else if (command === 'snooze') {
      world.nudge = null
      world.skips += 1
    } else if (command === 'done' && nudge) {
      if (nudge.started !== null) {
        said.took = Math.floor((clock.now() - nudge.started) / 1000)
      }

      world.nudge = null
    } else if (command === 'beep' && !world.hasBeeped) {
      world.hasBeeped = true
      said.beep = true
    }

    return ok(
      JSON.stringify({ now: clock.now(), nudge: world.nudge, stop: null, next: world.next, paused: world.paused, worked: world.worked, skips: world.skips, ...said })
    )
  })

  return world
}

test('the status line counts down to the next nudge, and it shows the second it is due', async ($, on) => {
  const clock = mock.clock(on, { now: START })
  const world = fakeBod(on, clock, null)
  world.next = { move: START + 182_000 }
  await $.session.start(SESSION)
  const ui = await $.ui.mount({ ...BAND, surface: 'terminal' })
  await clock.advance(1_000)

  expect(world.status).toBe('🤸 move in 3:01')

  await clock.advance(60_000)

  expect(world.status).toBe('🤸 move in 2:01')

  // Due at 3:02. The 5 second poll last ran at 3:00 and next runs at 3:05;
  // the mod asks bod.py itself the second the countdown ends.
  world.due = { at: START + 182_000, nudge: { kind: 'move', text: '10 squats', seconds: null, started: null } }
  await clock.advance(121_000)

  expect(await ui.find({ text: /squats/ })).toBeDefined()
  expect(world.status).toBeUndefined()
})

test('the status line says when Claude Bod is paused', async ($, on) => {
  const clock = mock.clock(on, { now: START })
  const world = fakeBod(on, clock, null)
  world.paused = true
  await $.session.start(SESSION)
  await clock.advance(1_000)

  expect(world.status).toBe('⏸ Claude Bod is paused until your next prompt')
})

test("the status line leads with today's hours, and keeps them while a nudge is on show", async ($, on) => {
  const clock = mock.clock(on, { now: START })
  const world = fakeBod(on, clock, null)
  world.next = { move: START + 182_000 }
  world.worked = 2 * 3600 + 5 * 60 + 30
  await $.session.start(SESSION)
  await clock.advance(1_000)

  expect(world.status).toBe('⏱ 2h 05m today · 🤸 move in 3:01')

  world.due = { at: START + 182_000, nudge: { kind: 'move', text: '10 squats', seconds: null, started: null } }
  world.worked = 14 * 60
  await clock.advance(182_000)

  expect(world.status).toBe('⏱ 14m today')
})

test('an exercise: go starts a timer that counts up, done ends it', async ($, on) => {
  const clock = mock.clock(on, { now: START })
  const world = fakeBod(on, clock, { kind: 'move', text: '10 squats', seconds: null })
  await $.session.start(SESSION)
  const ui = await $.ui.mount({ ...BAND, surface: 'terminal' })

  expect(await ui.find({ text: /Movement break: 10 squats/ })).toBeDefined()
  expect(await ui.find({ key: 'done' })).toBeUndefined()

  await ui.press({ key: 'go' })
  await clock.advance(23_000)

  expect((await ui.find({ type: 'Text', text: '⏱' }))?.text).toContain('0:23')
  expect(await ui.find({ key: 'go' })).toBeUndefined()

  await ui.press({ key: 'done' })

  expect(world.toasts).toEqual(['Nice, 0:23 💪'])
  expect(await ui.find({ text: /squats/ })).toBeUndefined()
})

test('a timed hold counts down and rings once at zero', async ($, on) => {
  const clock = mock.clock(on, { now: START })
  const world = fakeBod(on, clock, { kind: 'move', text: 'a 20 second plank', seconds: 20 })
  await $.session.start(SESSION)
  const ui = await $.ui.mount({ ...BAND, surface: 'terminal' })

  await ui.press({ key: 'go' })
  await clock.advance(5_000)

  expect((await ui.find({ type: 'Text', text: '⏱' }))?.text).toContain('0:15 left')
  expect(world.sounds).toBe(0)

  await clock.advance(20_000)

  expect((await ui.find({ type: 'Text', text: '⏱' }))?.text).toContain("time's up")
  expect(world.sounds).toBe(1)
  expect(world.commands.filter(command => command === 'beep')).toHaveLength(1)
})

test('a kindness nudge has done and no timer', async ($, on) => {
  const clock = mock.clock(on, { now: START })
  const world = fakeBod(on, clock, { kind: 'kind', text: 'take three slow breaths', seconds: null })
  await $.session.start(SESSION)
  const ui = await $.ui.mount({ ...BAND, surface: 'terminal' })

  expect(await ui.find({ text: /Be nice to yourself: take three slow breaths/ })).toBeDefined()
  expect(await ui.find({ key: 'go' })).toBeUndefined()

  await ui.press({ key: 'done' })

  expect(world.toasts).toEqual(['Nice 💛'])
})

test('a workflow check-in takes over the band with the question, one fix, done and not now', async ($, on) => {
  const clock = mock.clock(on, { now: START })
  const world = fakeBod(on, clock, { kind: 'check', text: 'close every tab whose PR has merged', seconds: null })
  await $.session.start(SESSION)
  const ui = await $.ui.mount({ ...BAND, surface: 'terminal' })

  expect(await ui.find({ text: /Workflow check-in/ })).toBeDefined()
  expect(await ui.find({ text: /Feeling the Claude-FOG\?/ })).toBeDefined()
  expect(await ui.find({ text: /Try this: close every tab whose PR has merged/ })).toBeDefined()
  expect(await ui.find({ key: 'go' })).toBeUndefined()
  expect(await ui.find({ key: 'snooze' })).toBeDefined()

  await ui.press({ key: 'done' })

  expect(world.commands).toContain('done')
})

test('no prompt is sent while a check-in is on show', async ($, on) => {
  const clock = mock.clock(on, { now: START })
  fakeBod(on, clock, { kind: 'check', text: 'close every tab whose PR has merged', seconds: null })
  await $.session.start(SESSION)

  const { drop } = await $.prompt.submit(PROMPT)

  expect(drop).toContain('🧭 Workflow check-in')
  expect(drop).toContain('Press done, or "not now"')
})

test('swap trades the exercise for a different one', async ($, on) => {
  const clock = mock.clock(on, { now: START })
  const world = fakeBod(on, clock, { kind: 'move', text: '10 jumping jacks', seconds: null })
  await $.session.start(SESSION)
  const ui = await $.ui.mount({ ...BAND, surface: 'terminal' })

  await ui.press({ key: 'swap' })

  expect(world.commands).toContain('swap')
  expect(await ui.find({ text: /calf raises/ })).toBeDefined()
  expect(await ui.find({ text: /jumping jacks/ })).toBeUndefined()
})

test('a kindness nudge and a running timer have no swap', async ($, on) => {
  const clock = mock.clock(on, { now: START })
  const world = fakeBod(on, clock, { kind: 'kind', text: 'you are doing fine', seconds: null })
  await $.session.start(SESSION)
  const ui = await $.ui.mount({ ...BAND, surface: 'terminal' })

  expect(await ui.find({ key: 'swap' })).toBeUndefined()

  world.nudge = { kind: 'move', text: '10 squats', seconds: null, started: START }
  await clock.advance(1_000)

  expect(await ui.find({ key: 'swap' })).toBeUndefined()
})

test('not now takes the nudge off the band', async ($, on) => {
  const clock = mock.clock(on, { now: START })
  const world = fakeBod(on, clock, { kind: 'move', text: '10 squats', seconds: null })
  await $.session.start(SESSION)
  const ui = await $.ui.mount({ ...BAND, surface: 'terminal' })

  await ui.press({ key: 'snooze' })

  expect(world.commands).toContain('snooze')
  expect(await ui.find({ text: /squats/ })).toBeUndefined()
})

test('the status line counts the day\'s skips, and a nudge that comes back says it was skipped', async ($, on) => {
  const clock = mock.clock(on, { now: START })
  const world = fakeBod(on, clock, { kind: 'move', text: '10 squats', seconds: null })
  world.next = { move: START + 182_000 }
  await $.session.start(SESSION)
  const ui = await $.ui.mount({ ...BAND, surface: 'terminal', props: { ...BAND.props, maxRows: 20 } })

  await ui.press({ key: 'snooze' })
  await clock.advance(1_000)

  expect(world.status).toBe('🤸 move in 3:01 · 🙈 1 skipped today')

  world.nudge = { kind: 'move', text: '10 squats', seconds: null, started: null, skipped: 1 }
  world.next = null
  await clock.advance(5_000)

  expect(await ui.find({ text: /you skipped once already/ })).toBeDefined()
  expect(world.status).toBe('🙈 1 skipped today')
})

test('a nudge another session raised shows up on the next poll', async ($, on) => {
  const clock = mock.clock(on, { now: START })
  const world = fakeBod(on, clock, null)
  await $.session.start(SESSION)
  const ui = await $.ui.mount({ ...BAND, surface: 'terminal' })

  expect(await ui.find({ key: 'go' })).toBeUndefined()

  world.nudge = { kind: 'move', text: '10 calf raises', seconds: null, started: null }
  await clock.advance(5_000)

  expect(await ui.find({ text: /calf raises/ })).toBeDefined()
  expect(await ui.find({ key: 'go' })).toBeDefined()
})

test('an exercise set takes over the band in a box, one exercise per line, never a side panel', async ($, on) => {
  const clock = mock.clock(on, { now: START })
  const world = fakeBod(on, clock, { kind: 'move', text: '8 push ups, then 15 jumping jacks, then 15 squats', seconds: null })
  world.isWide = true
  await $.session.start(SESSION)
  const ui = await $.ui.mount({ ...BAND, props: { ...BAND.props, maxRows: 20 }, surface: 'terminal' })

  expect(world.isPanelOpen).toBe(false)
  expect(await ui.find({ text: '1. 8 push ups' })).toBeDefined()
  expect(await ui.find({ text: '2. 15 jumping jacks' })).toBeDefined()
  expect(await ui.find({ text: '3. 15 squats' })).toBeDefined()

  await ui.press({ key: 'go' })
  await clock.advance(7_000)

  expect(await ui.find({ type: 'Text', text: '⏱ 0:07' })).toBeDefined()

  await ui.press({ key: 'done' })

  expect(world.toasts).toEqual(['Nice, 0:07 💪'])
  expect(await ui.find({ text: /squats/ })).toBeUndefined()
})

test('where the band is too short for the box, the nudge is one line', async ($, on) => {
  const clock = mock.clock(on, { now: START })
  fakeBod(on, clock, { kind: 'move', text: '8 push ups, then 15 jumping jacks, then 15 squats', seconds: null })
  await $.session.start(SESSION)
  const ui = await $.ui.mount({ ...BAND, surface: 'terminal' })

  expect(await ui.find({ text: /Movement break: 8 push ups → 15 jumping jacks → 15 squats/ })).toBeDefined()
  expect(await ui.find({ key: 'go' })).toBeDefined()
})

test('no prompt is sent while an exercise is on show, and her words are left for Claude Code to put back', async ($, on) => {
  const clock = mock.clock(on, { now: START })
  const world = fakeBod(on, clock, { kind: 'move', text: '10 squats', seconds: null })
  await $.session.start(SESSION)
  const ui = await $.ui.mount({ ...BAND, surface: 'terminal' })

  expect((await $.prompt.submit(PROMPT)).drop).toContain('Movement break: 10 squats first!')
  expect(world.refilled).toEqual([])

  await ui.press({ key: 'go' })

  expect((await $.prompt.submit(PROMPT)).drop).toBeDefined()

  await ui.press({ key: 'done' })

  expect(await $.prompt.submit(PROMPT)).toEqual({ text: 'fix the bug' })
})

test('not now lets prompts through again', async ($, on) => {
  const clock = mock.clock(on, { now: START })
  fakeBod(on, clock, { kind: 'move', text: '10 squats', seconds: null })
  await $.session.start(SESSION)
  const ui = await $.ui.mount({ ...BAND, surface: 'terminal' })

  await ui.press({ key: 'snooze' })

  expect(await $.prompt.submit(PROMPT)).toEqual({ text: 'fix the bug' })
})

test('a kindness nudge never holds a prompt back', async ($, on) => {
  const clock = mock.clock(on, { now: START })
  const world = fakeBod(on, clock, { kind: 'kind', text: 'take three slow breaths', seconds: null })
  await $.session.start(SESSION)

  expect(await $.prompt.submit(PROMPT)).toEqual({ text: 'fix the bug' })
  expect(world.isPanelOpen).toBe(false)
})

test('a broken bod.py never locks her out', async ($, on) => {
  const clock = mock.clock(on, { now: START })
  const world = fakeBod(on, clock, { kind: 'move', text: '10 squats', seconds: null })
  world.isWide = true
  await $.session.start(SESSION)
  world.isBroken = true

  expect(await $.prompt.submit(PROMPT)).toEqual({ text: 'fix the bug' })
  expect(world.isPanelOpen).toBe(false)
})

test('a session past the Claude cap has its prompt refused, and her words are left for Claude Code to put back', async ($, on) => {
  const clock = mock.clock(on, { now: START })
  const world = fakeBod(on, clock, null)
  await $.session.start(SESSION)
  world.limit = JSON.stringify({ decision: 'block', reason: 'You have 6 Claudes open — the limit is 4.' })

  expect(await $.prompt.submit(PROMPT)).toEqual({ drop: '🧠 You have 6 Claudes open — the limit is 4.' })
  expect(world.refilled).toEqual([])

  world.limit = ''
  expect(await $.prompt.submit(PROMPT)).toEqual({ text: 'fix the bug' })
})

test('a broken claude-limit.py lets prompts through', async ($, on) => {
  const clock = mock.clock(on, { now: START })
  const world = fakeBod(on, clock, null)
  await $.session.start(SESSION)
  world.isBroken = true

  expect(await $.prompt.submit(PROMPT)).toEqual({ text: 'fix the bug' })
})

test('every prompt is recorded as work', async ($, on) => {
  const clock = mock.clock(on, { now: START })
  const world = fakeBod(on, clock, null)
  await $.session.start(SESSION)
  await $.prompt.submit(PROMPT)

  expect(world.commands).toContain('hook')
})

test('/bod level, /bod every, /bod claudes and the on/off switches set Claude Bod, and /bod alone says what it is set to', async ($, on) => {
  const clock = mock.clock(on, { now: START })
  const world = fakeBod(on, clock, null)
  await $.session.start(SESSION)

  expect(await $.command.run(BOD('level hard'))).toMatchObject({ text: 'Claude Bod is on hard.' })
  expect(await $.command.run(BOD(' every 10 '))).toMatchObject({ text: 'Claude Bod is on 10.' })
  expect(world.commands).toContain('level hard')
  expect(world.commands).toContain('every 10')
  await $.command.run(BOD('level hard every 15'))
  expect(world.commands).toContain('level hard every 15')
  expect(await $.command.run(BOD('claudes 5'))).toMatchObject({ text: 'Claude Bod is on 5.' })
  expect(world.commands).toContain('claudes 5')
  expect(await $.command.run(BOD('move off'))).toMatchObject({ text: 'Claude Bod is on off.' })
  expect(world.commands).toContain('move off')
  expect(await $.command.run(BOD('check off'))).toMatchObject({ text: 'Claude Bod is on off.' })
  expect(world.commands).toContain('check off')
  expect(await $.command.run(BOD('info'))).toMatchObject({ text: 'Claude Bod settings:\n- Claude cap: 5' })
  expect(world.isPanelOpen).toBe(false)

  expect(await $.command.run(BOD(''))).toMatchObject({ text: 'Claude Bod is on easy. /bod now for an exercise right away.' })
  expect(world.isPanelOpen).toBe(false)
})

test('/bod now puts an exercise up at once, in the band', async ($, on) => {
  const clock = mock.clock(on, { now: START })
  const world = fakeBod(on, clock, null)
  await $.session.start(SESSION)
  const ui = await $.ui.mount({ ...BAND, surface: 'terminal' })

  expect(await ui.find({ key: 'go' })).toBeUndefined()

  world.due = { at: START, nudge: { kind: 'move', text: '10 squats', seconds: null, started: null } }
  expect(await $.command.run(BOD('now'))).toMatchObject({ text: '🤸 Movement break: 10 squats' })
  expect(world.commands).toContain('now')
  expect(world.isPanelOpen).toBe(false)
  expect(await ui.find({ key: 'go' })).toBeDefined()
})

test('/bod kind now puts a kindness nudge up at once, and isn\'t a setting', async ($, on) => {
  const clock = mock.clock(on, { now: START })
  const world = fakeBod(on, clock, null)
  await $.session.start(SESSION)

  world.due = { at: START, nudge: { kind: 'kind', text: 'take a breath', seconds: null, started: null } }
  expect(await $.command.run(BOD('kind now'))).toMatchObject({ text: '💛 Be nice to yourself: take a breath' })
  expect(world.commands).toContain('kindnow')
  expect(world.commands).not.toContain('kind now')
})

test('/bod move now is /bod now, and isn\'t a setting', async ($, on) => {
  const clock = mock.clock(on, { now: START })
  const world = fakeBod(on, clock, null)
  await $.session.start(SESSION)

  world.due = { at: START, nudge: { kind: 'move', text: '10 squats', seconds: null, started: null } }
  expect(await $.command.run(BOD('move now'))).toMatchObject({ text: '🤸 Movement break: 10 squats' })
  expect(world.commands).toContain('now')
  expect(world.commands).not.toContain('move now')
})

test('done adds "✅ Nice job!" to the chat, beside the toast', async ($, on) => {
  const clock = mock.clock(on, { now: START })
  const world = fakeBod(on, clock, { kind: 'move', text: '10 squats', seconds: null })
  await $.session.start(SESSION)
  const band = await $.ui.mount({ ...BAND, surface: 'terminal' })

  await band.press({ key: 'go' })
  await clock.advance(42_000)
  await band.press({ key: 'done' })

  expect(world.toasts).toEqual(['Nice, 0:42 💪'])
  expect(world.logs).toEqual(['✅ Nice job! 0:42'])
})

test('a kindness nudge done says "✅ Nice job!" with no time', async ($, on) => {
  const clock = mock.clock(on, { now: START })
  const world = fakeBod(on, clock, { kind: 'kind', text: 'take three slow breaths', seconds: null })
  await $.session.start(SESSION)
  const band = await $.ui.mount({ ...BAND, surface: 'terminal' })

  await band.press({ key: 'done' })

  expect(world.logs).toEqual(['✅ Nice job!'])
})

const FORM = {
  plugin: 'bod',
  component: 'Pane',
  requestId: 'bod-config',
  surface: 'terminal',
  props: {
    title: 'Claude Bod settings',
    isFocused: true,
    bodyColumns: 60,
    placement: 'inline',
    scroll: { offset: 0, bodyRows: 8 },
    view: {},
  },
} as const

test('/bod config opens one form with every setting at its current value, and Save sends only what changed', async ($, on) => {
  const clock = mock.clock(on, { now: START })
  const world = fakeBod(on, clock, null)
  world.isWide = true
  await $.session.start(SESSION)

  expect(await $.command.run(BOD('config'))).toMatchObject({ text: 'Claude Bod settings: change what you like, then Save (Esc to cancel).' })
  expect(world.isPanelOpen).toBe(true)

  const ui = await $.ui.mount(FORM)
  expect((await ui.find({ type: 'Button', key: 'level' }))?.props).toMatchObject({ autoFocus: true })
  expect((await ui.find({ type: 'Button', key: 'kind' }))?.text).toMatch(/^Kindness every +15 min$/)

  // Enter steps a row to its next value, back to the first after the last.
  await ui.press({ key: 'kind' })
  await ui.press({ key: 'kind' })
  await ui.press({ key: 'snooze' })
  await ui.press({ key: 'level' })
  await ui.press({ key: 'level' })
  await ui.press({ key: 'level' })
  await ui.press({ key: 'level' })
  expect((await ui.find({ type: 'Button', key: 'kind' }))?.text).toMatch(/45 min \(was 15 min\)$/)
  expect((await ui.find({ type: 'Button', key: 'level' }))?.text).toMatch(/easy$/)
  // Each nudge has its own on/off row.
  await ui.press({ key: 'check' })
  expect((await ui.find({ type: 'Button', key: 'check' }))?.text).toMatch(/^Check-in +off \(was on\)$/)
  await ui.press({ key: 'save' })

  expect(world.commands).toContain('kind 45 check off snooze 10')
  expect(world.logs).toEqual(['Claude Bod is on 45 check off snooze 10.'])
  expect(world.isPanelOpen).toBe(false)
  await ui.unmount()
})

test('/bod config Save with nothing changed says so, and Cancel saves nothing', async ($, on) => {
  const clock = mock.clock(on, { now: START })
  const world = fakeBod(on, clock, null)
  world.isWide = true
  await $.session.start(SESSION)

  await $.command.run(BOD('config'))
  let ui = await $.ui.mount(FORM)
  await ui.press({ key: 'save' })
  expect(world.logs).toEqual(['Nothing changed.'])
  await ui.unmount()

  await $.command.run(BOD('config'))
  ui = await $.ui.mount(FORM)
  await ui.press({ key: 'level' })
  await ui.press({ key: 'cancel' })
  expect(world.isPanelOpen).toBe(false)
  expect(world.commands.filter(c => c.startsWith('level'))).toEqual([])
  await ui.unmount()
})

test('/bod config asks for the keys again once the command is done, so the arrows reach the form', async ($, on) => {
  const clock = mock.clock(on, { now: START })
  const world = fakeBod(on, clock, null)
  world.isWide = true
  await $.session.start(SESSION)

  await $.command.run(BOD('config'))
  expect(world.opens).toHaveLength(1)

  await clock.advance(300)
  expect(world.opens).toHaveLength(2)
  expect(world.opens[1]).toMatchObject({ id: 'bod-config', focus: true })
})

test('/bod config lists the settings instead when the form cannot be drawn', async ($, on) => {
  const clock = mock.clock(on, { now: START })
  const world = fakeBod(on, clock, null)
  await $.session.start(SESSION)

  expect(await $.command.run(BOD('config'))).toMatchObject({ text: 'Claude Bod settings:\n- Claude cap: 5' })
  expect(world.isPanelOpen).toBe(false)
})

test('/bod with something it does not know says so and points at info and config', async ($, on) => {
  const clock = mock.clock(on, { now: START })
  fakeBod(on, clock, null)
  await $.session.start(SESSION)

  expect(await $.command.run(BOD('can i set my snooze?'))).toMatchObject({
    text: 'Claude Bod doesn\'t know "/bod can i set my snooze?". /bod info lists every setting and /bod config sets them all in one form.',
  })
  expect(await $.command.run(BOD('snooze 10'))).toMatchObject({ text: 'Claude Bod is on 10.' })
})
