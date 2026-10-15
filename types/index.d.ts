/** The nudge on show, as `bod.py` prints it; times are epoch milliseconds. */
export type Nudge = {
  kind: 'move' | 'stand' | 'kind'
  text: string
  /** Seconds to count down from once started; null counts up instead. */
  seconds: number | null
  /** When go was pressed; null until then. */
  started: number | null
}

/** What the band draws from. */
export type View = {
  nudge: Nudge | null
  /** The "stop for the day" line, once today's hours are past the cap. */
  stop: string | null
  /** When the exercise / standing nudges are next due; null while one is on show. */
  next?: { move?: number; stand?: number } | null
  /** She's been away long enough that nothing shows until her next prompt. */
  paused?: boolean
}

/** What `bod.py tick` and each button print: the view, and what just happened. */
export type Reply = View & {
  now: number
  /** After done: how many seconds the exercise took, when it was timed. */
  took?: number
  /** After beep: this session is the one that plays the sound. */
  beep?: boolean
}

declare module 'claude-code' {
  interface PluginState {
    'bod': { view: View | null; now: number }
  }
}
