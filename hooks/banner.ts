// Giant letters for the takeover panel. A terminal can't draw a bigger font,
// so each character is built from block cells, five rows tall.
const ROWS = 5

const GLYPHS: Record<string, readonly string[]> = {
  A: [' ███ ', '█   █', '█████', '█   █', '█   █'],
  B: ['████ ', '█   █', '████ ', '█   █', '████ '],
  C: [' ████', '█    ', '█    ', '█    ', ' ████'],
  D: ['████ ', '█   █', '█   █', '█   █', '████ '],
  E: ['█████', '█    ', '████ ', '█    ', '█████'],
  F: ['█████', '█    ', '████ ', '█    ', '█    '],
  G: [' ████', '█    ', '█  ██', '█   █', ' ████'],
  H: ['█   █', '█   █', '█████', '█   █', '█   █'],
  I: ['███', ' █ ', ' █ ', ' █ ', '███'],
  J: ['  ███', '   █ ', '   █ ', '█  █ ', ' ██  '],
  K: ['█   █', '█  █ ', '███  ', '█  █ ', '█   █'],
  L: ['█    ', '█    ', '█    ', '█    ', '█████'],
  M: ['█   █', '██ ██', '█ █ █', '█   █', '█   █'],
  N: ['█   █', '██  █', '█ █ █', '█  ██', '█   █'],
  O: [' ███ ', '█   █', '█   █', '█   █', ' ███ '],
  P: ['████ ', '█   █', '████ ', '█    ', '█    '],
  Q: [' ███ ', '█   █', '█ █ █', '█  █ ', ' ██ █'],
  R: ['████ ', '█   █', '████ ', '█  █ ', '█   █'],
  S: [' ████', '█    ', ' ███ ', '    █', '████ '],
  T: ['█████', '  █  ', '  █  ', '  █  ', '  █  '],
  U: ['█   █', '█   █', '█   █', '█   █', ' ███ '],
  V: ['█   █', '█   █', '█   █', ' █ █ ', '  █  '],
  W: ['█   █', '█   █', '█ █ █', '██ ██', '█   █'],
  X: ['█   █', ' █ █ ', '  █  ', ' █ █ ', '█   █'],
  Y: ['█   █', ' █ █ ', '  █  ', '  █  ', '  █  '],
  Z: ['█████', '   █ ', '  █  ', ' █   ', '█████'],
  0: [' ███ ', '█  ██', '█ █ █', '██  █', ' ███ '],
  1: [' █ ', '██ ', ' █ ', ' █ ', '███'],
  2: ['████ ', '    █', ' ███ ', '█    ', '█████'],
  3: ['████ ', '    █', ' ███ ', '    █', '████ '],
  4: ['█   █', '█   █', '█████', '    █', '    █'],
  5: ['█████', '█    ', '████ ', '    █', '████ '],
  6: [' ███ ', '█    ', '████ ', '█   █', ' ███ '],
  7: ['█████', '    █', '   █ ', '  █  ', '  █  '],
  8: [' ███ ', '█   █', ' ███ ', '█   █', ' ███ '],
  9: [' ███ ', '█   █', ' ████', '    █', ' ███ '],
  ':': [' ', '█', ' ', '█', ' '],
  '!': ['█', '█', '█', ' ', '█'],
}

const WORD_GAP = 3

// One word as its five rows; characters with no glyph are left out.
const word = (text: string) => {
  const glyphs = [...text.toUpperCase()].flatMap(char => (GLYPHS[char] ? [GLYPHS[char]] : []))

  return Array.from({ length: ROWS }, (_, row) => glyphs.map(glyph => glyph[row]).join(' '))
}

const width = (rows: readonly string[]) => rows[0]?.length ?? 0

/**
 * `text` in giant letters: its rows, top to bottom, no row wider than
 * `columns`. Words that don't fit side by side go on a line of their own, with
 * a blank row between lines; a single word wider than `columns` is cut.
 */
export const banner = (text: string, columns: number): string[] => {
  const lines: string[][] = []

  for (const next of text.split(/\s+/).map(word).filter(rows => width(rows) > 0)) {
    const line = lines.at(-1)

    if (line && width(line) + WORD_GAP + width(next) <= columns) {
      lines[lines.length - 1] = line.map((row, index) => row + ' '.repeat(WORD_GAP) + next[index])
    } else {
      lines.push(next)
    }
  }

  return lines.flatMap((line, index) => [...(index > 0 ? [''] : []), ...line.map(row => row.slice(0, columns))])
}
