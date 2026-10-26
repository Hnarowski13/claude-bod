/** The nudge on show, as `bod.py` prints it; times are epoch milliseconds. */
export type Nudge = {
  kind: 'move' | 'kind' | 'check'
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
  /** When the exercise nudge is next due; null while a nudge is on show. */
  next?: { move?: number } | null
  /** She's been away long enough that nothing shows until her next prompt. */
  paused?: boolean
  /** Seconds worked today, for the status line; null when they couldn't be counted. */
  worked?: number | null
  /** How many times she's said "not now" today, for the status line. */
  skips?: number
}

/** What `bod.py tick` and each button print: the view, and what just happened. */
export type Reply = View & {
  now: number
  /** After done: how many seconds the exercise took, when it was timed. */
  took?: number
  /** After beep: this session is the one that plays the sound. */
  beep?: boolean
}

/** A setting `/bod config` shows a row for, as bod.py names it. */
export type Setting = 'level' | 'every' | 'kind' | 'check' | 'claudes' | 'snooze'

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
