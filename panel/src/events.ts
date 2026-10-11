/**
 * История событий текущей сессии панели (лента на дашборде, §5.4).
 * Это клиентские события — серверная лента /api/logs появится на этапе 4.
 */

import type { OrbState } from "./ui";

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

// ── Состояние ассистента ─────────────────────────────────────────
// Экраны (чат, голосовой режим) знают, что ассистент делает прямо сейчас,
// а показывает это орб в статус-строке. Связь — через событие документа:
// экран не держит вторую копию орба и не тянет статус-строку за собой.

export const ASSISTANT_STATE_EVENT = "zere-assistant-state";

export interface AssistantStateDetail {
  state: OrbState;
  label?: string;
}

export function announceAssistantState(state: OrbState, label: string): void {
  document.dispatchEvent(
    new CustomEvent<AssistantStateDetail>(ASSISTANT_STATE_EVENT, {
      detail: { state, label },
    }),
  );
}
