/**
 * Экран «Личности» (§6, гейт этапа 2): карточки стилей строятся из
 * ФАКТИЧЕСКОГО списка /api/personality (урок отчёта «6 стилей → 5»,
 * без хардкода), смена стиля идёт через POST /api/personality/set и
 * сохраняется — переживает рестарт (чинит P1-3).
 */

import { ApiError, apiGet, apiPost, type Personality } from "../api";
import { logEvent } from "../events";
import { t } from "../i18n";
import {
  badge,
  clear,
  emptyState,
  h,
  loadingRow,
  pageHeader,
  toast,
} from "../ui";
import type { Cleanup, ScreenFactory } from "../router";

/** Метаданные встроенной личности (JARVIS.Core/Plugins/BuiltIn). */
const STYLE_META: Record<string, { temperature: string; description: string }> = {
  Friendly: { temperature: "0.7", description: "Дружелюбный, тёплый, с эмодзи" },
  Formal: { temperature: "0.3", description: "Официальный, строгий, профессиональный" },
  Sarcastic: { temperature: "0.9", description: "Саркастичный, с иронией и юмором" },
  Professional: { temperature: "0.4", description: "Деловой, без лишних слов" },
  Casual: { temperature: "0.8", description: "Неформальный, на «ты»" },
};

export const personalitiesScreen: ScreenFactory = (container): Cleanup => {
  let cancelled = false;
  let pending = false;

  const render = (personality: Personality | null, error?: string): void => {
    clear(container);

    if (!personality) {
      container.appendChild(
        emptyState({
          icon: "⚠️",
          title: t("Не удалось загрузить личности"),
          hint: error ?? t("Неизвестная ошибка"),
          action: { label: t("Повторить"), onClick: () => void load() },
        }),
      );
      return;
    }

    const p = personality;

    container.appendChild(
      pageHeader(
        t("Личности"),
        t("Активная личность: {id} · стиль {style}", { id: p.activeId, style: p.activeStyle }),
        [badge(t("стилей: {count}", { count: p.styles.length }), "accent")],
      ),
    );

    if (error) {
      container.appendChild(h("div", { class: "form-error", text: error }));
    }

    container.appendChild(
      h(
        "div",
        { class: "panel-note" },
        t("Стиль сохраняется в config/plugins.json и переживает рестарт ассистента."),
      ),
    );

    const grid = h("div", { class: "style-grid fade-in" });

    for (const style of p.styles) {
      const meta = STYLE_META[style];
      const isActive = style === p.activeStyle;

      const cardEl = h(
        "button",
        {
          class: isActive ? "style-card style-card--active" : "style-card",
          type: "button",
          disabled: pending,
          onclick: () => void setStyle(style, p),
        },
        h(
          "div",
          { class: "style-card__head" },
          h("span", { class: "style-card__name", text: style }),
          isActive ? badge(t("активный"), "accent") : null,
        ),
        h("div", { class: "style-card__desc", text: meta ? t(meta.description) : t("Описание появится позже") }),
        h("span", {
          class: "style-card__temp",
          text: meta ? `t = ${meta.temperature}` : "t = —",
        }),
      );

      grid.appendChild(cardEl);
    }

    container.appendChild(grid);
  };

  const setStyle = async (styleId: string, previous: Personality): Promise<void> => {
    if (pending) return;
    pending = true;
    render(previous);

    try {
      const updated = await apiPost<Personality>("/api/personality/set", { styleId });

      if (cancelled) return;

      pending = false;
      render(updated);
      toast(t("Стиль «{name}» сохранён — переживёт рестарт", { name: updated.activeStyle }), "ok");
      logEvent(`Стиль личности изменён: ${updated.activeStyle}`);
    } catch (error) {
      if (cancelled) return;

      pending = false;
      const message = error instanceof ApiError ? error.message : t("Неизвестная ошибка");
      render(previous, message);
      toast(t("Не удалось сменить стиль"), "danger");
      logEvent(`Ошибка смены стиля: ${message}`);
    }
  };

  const load = async (): Promise<void> => {
    clear(container);
    container.appendChild(loadingRow(t("Загрузка личностей…")));

    try {
      const personality = await apiGet<Personality>("/api/personality");

      if (cancelled) return;
      render(personality);
    } catch (error) {
      if (cancelled) return;
      const message = error instanceof Error ? error.message : t("Неизвестная ошибка");
      render(null, message);
    }
  };

  void load();

  return () => {
    cancelled = true;
  };
};
