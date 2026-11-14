// Small helpers over localStorage. Storage can be blocked or full (private windows, strict
// settings), so every read and write is allowed to fail quietly.

export function load(key, fallback) {
  try {
    const raw = window.localStorage.getItem(key);
    return raw ? JSON.parse(raw) : fallback;
  } catch {
    return fallback;
  }
}

export function save(key, value) {
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // Nothing to do: the page works without storage.
  }
}
