// Which way a story is told: in the glossary's business words, or with technical names.
// The choice is kept per browser, and everything still works when storage is blocked.

export type WordsMode = "business" | "technical";

export const WORDS_MODE_KEY = "openpipeline.words";

export function readWordsMode(): WordsMode {
  try {
    return localStorage.getItem(WORDS_MODE_KEY) === "business" ? "business" : "technical";
  } catch {
    return "technical";
  }
}

export function saveWordsMode(mode: WordsMode): void {
  try {
    localStorage.setItem(WORDS_MODE_KEY, mode);
  } catch {
    // Private windows and blocked storage: the choice just lasts until the page closes.
  }
}
