/** The nudge on show, as `bod.py` prints it; times are epoch milliseconds. */
export type Nudge = {
  kind: 'move' | 'kind' | 'check' | 'music'
  text: string
  /** Seconds to count down from once started; null counts up instead. */
  seconds: number | null
  /** When go was pressed; null until then. */
  started: number | null
  /** How many times this nudge was put off with "not now". */
  skipped?: number
}

/** What the band draws from. */
export type View = {
  nudge: Nudge | null
  /** The "stop for the day" line, once today's hours are past the cap. */
  stop: string | null
  /** When the exercise and kindness nudges are next due, each left out while it's off; null while a nudge is on show. */
  next?: { move?: number; kind?: number } | null
  /** She's been away long enough that nothing shows until her next prompt. */
  paused?: boolean
  /** Seconds worked today, for the status line; null when they couldn't be counted. */
  worked?: number | null
  /** How many times she's said "not now" today, for the status line. */
  skips?: number
  /** Today's merged PRs (a Bod PR counts as half) and the daily cap, for the status line; null when GitHub couldn't be asked. */
  merged?: { count: number; cap: number } | null
  /** Where the focus session stands: running, wrapping up, on the break after, or none running. */
  focus?: Focus | null
  /** Why prompts are refused: today's hours are past the hard cap, or no focus session is running. Null while they go through. */
  locked?: string | null
}

/** The focus session, as `bod.py` prints it. */
export type Focus = {
  phase: 'working' | 'wrap-up' | 'break' | 'none'
  /** When this phase ends, in epoch milliseconds; null when no session is running. */
  ends: number | null
  /** What she said she wants to get done; null when no session is running. */
  goal: string | null
  /** The band's line: time to wrap up, or why prompts are refused; null while the session runs. */
  line: string | null
}

/** What `bod.py tick` and each button print: the view, and what just happened. */
export type Reply = View & {
  now: number
  /** After done: how many seconds the exercise took, when it was timed. */
  took?: number
  /** After beep: this session is the one that plays the sound. */
  beep?: boolean
  /** After tick: a focus session just reached wrap-up or its break, and this session plays that sound. */
  sound?: 'wrap-up' | 'break'
}

/** A setting `/bod config` shows a row for, as bod.py names it. */
export type Setting = 'level' | 'move' | 'every' | 'kindness' | 'kind' | 'check' | 'music' | 'claudes' | 'snooze'

/** The `/bod config` form while it's open: what's saved, what she's picked, what each may be. */
export type Form = {
  saved: Record<Setting, string>
  picked: Record<Setting, string>
  choices: Record<Setting, string[]>
}

declare module 'claude-code' {
  interface PluginState {
    'bod': { view: View | null; now: number; form: Form | null }
  }
}
