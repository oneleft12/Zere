/**
 * История событий текущей сессии панели (лента на дашборде, §5.4).
 * Это клиентские события — серверная лента /api/logs появится на этапе 4.
 */

export interface SessionEvent {
  time: Date;
  text: string;
}

const LIMIT = 20;
const events: SessionEvent[] = [];
const listeners = new Set<() => void>();

export function logEvent(text: string): void {
  events.unshift({ time: new Date(), text });

  if (events.length > LIMIT) events.length = LIMIT;

  for (const listener of listeners) listener();
}

export function getEvents(): SessionEvent[] {
  return events.slice();
}

export function subscribeEvents(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
