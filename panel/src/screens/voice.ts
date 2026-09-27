/**
 * Экран «Голос» (этап 4, §6): настройки через POST /api/voice (строгое
 * подмножество ключей), честные capabilities реализации и тесты:
 * озвучка фразы, запись референса (ConfirmDialog — микрофон!), распознавание.
 * Громкость применяется сразу (liveVolumeApply), остальное — после рестарта.
 */

import {
  ApiError,
  apiGet,
  apiPost,
  type VoiceSettings,
  type VoiceSettingsApplied,
} from "../api";
import { logEvent } from "../events";
import {
  badge,
  button,
  card,
  clear,
  confirmDialog,
  emptyState,
  field,
  h,
  keyValue,
  loadingRow,
  pageHeader,
  select,
  slider,
  textInput,
  toast,
  toggle,
} from "../ui";
import type { Cleanup, ScreenFactory } from "../router";

const MAX_TEST_TEXT = 500;

interface Draft {
  voiceEnabled: boolean;
  voiceVolume: number;
  ttsEngine: VoiceSettings["ttsEngine"];
  voiceReferencePath: string;
}

function toDraft(settings: VoiceSettings): Draft {
  return {
    voiceEnabled: settings.voiceEnabled,
    voiceVolume: settings.voiceVolume,
    ttsEngine: settings.ttsEngine,
    voiceReferencePath: settings.voiceReferencePath,
  };
}

function isDirty(base: VoiceSettings, draft: Draft): boolean {
  return (
    base.voiceEnabled !== draft.voiceEnabled ||
    base.voiceVolume !== draft.voiceVolume ||
    base.ttsEngine !== draft.ttsEngine ||
    base.voiceReferencePath !== draft.voiceReferencePath
  );
}

export const voiceScreen: ScreenFactory = (container): Cleanup => {
  let cancelled = false;

  container.appendChild(loadingRow("Загрузка голосовых настроек…"));

  const load = async (): Promise<void> => {
    if (cancelled) return;
    clear(container);
    container.appendChild(loadingRow("Загрузка голосовых настроек…"));

    try {
      const settings = await apiGet<VoiceSettings>("/api/voice");

      if (cancelled) return;
      render(settings, toDraft(settings));
    } catch (error) {
      if (cancelled) return;
      clear(container);
      container.appendChild(
        emptyState({
          icon: "⚠️",
          title: "Не удалось загрузить голосовые настройки",
          hint: error instanceof ApiError ? error.message : "Неизвестная ошибка",
          action: { label: "Повторить", onClick: () => void load() },
        }),
      );
    }
  };

  function render(base: VoiceSettings, draft: Draft): void {
    clear(container);

    const saveBtn = button("Сохранить", () => void save(), "primary");
    const revertBtn = button("Отменить изменения", () => {
      render(base, toDraft(base));
      logEvent("Изменения голосовых настроек отброшены");
    });

    const errorBox = h("div", { class: "form-error", hidden: true });
    const testErrorBox = h("div", { class: "form-error", hidden: true });
    const testResult = h("p", { class: "panel-note", hidden: true });

    const updateDirty = (): void => {
      saveBtn.disabled = !isDirty(base, draft);
      revertBtn.disabled = !isDirty(base, draft);
    };

    async function save(): Promise<void> {
      if (!isDirty(base, draft)) return;

      saveBtn.disabled = true;

      try {
        const applied = await apiPost<VoiceSettingsApplied>("/api/voice", draft);

        if (cancelled) return;

        const next: VoiceSettings = {
          voiceEnabled: applied.voiceEnabled,
          voiceVolume: applied.voiceVolume,
          ttsEngine: applied.ttsEngine,
          voiceReferencePath: applied.voiceReferencePath,
          capabilities: base.capabilities,
        };

        toast(
          applied.appliedOnRestart
            ? "Сохранено — вступит в силу после перезапуска"
            : "Громкость применена сразу",
          applied.appliedOnRestart ? "warn" : "ok",
        );
        logEvent(
          applied.appliedOnRestart
            ? "Голосовые настройки сохранены (перезапуск требуется)"
            : "Громкость голоса применена без перезапуска",
        );
        render(next, toDraft(next));
      } catch (error) {
        if (cancelled) return;

        const message = error instanceof Error ? error.message : "Неизвестная ошибка";
        errorBox.textContent = `Сервер отклонил настройки: ${message}`;
        errorBox.hidden = false;
        toast("Ошибка сохранения голосовых настроек", "danger");
        logEvent("Ошибка сохранения голоса");
        saveBtn.disabled = false;
      }
    }

    // ── Карточка настроек ────────────────────────────────────────
    const settingsCard = card(
      "Голосовой вывод",
      h(
        "div",
        { class: "form-grid form-grid--single" },
        toggle({
          label: "Голосовой вывод включён",
          checked: draft.voiceEnabled,
          onChange: (v) => {
            draft.voiceEnabled = v;
            updateDirty();
          },
        }),
        field(
          "Громкость",
          slider({
            value: draft.voiceVolume,
            min: 0,
            max: 1,
            step: 0.05,
            onChange: (v) => {
              draft.voiceVolume = v;
              updateDirty();
            },
          }),
          "Применяется сразу, без перезапуска",
        ),
        field(
          "TTS-движок",
          select({
            value: draft.ttsEngine,
            options: [
              { value: "pocket", label: "pocket — клонирование голоса" },
              { value: "piper", label: "piper — быстрый, без клонирования" },
            ],
            onChange: (v) => {
              draft.ttsEngine = v as Draft["ttsEngine"];
              updateDirty();
            },
          }),
          "Смена движка вступает в силу после перезапуска",
        ),
        field(
          "Референс голоса (WAV)",
          textInput({
            value: draft.voiceReferencePath,
            mono: true,
            placeholder: "путь к WAV-референсу, пусто = встроенный голос",
            onInput: (v) => {
              draft.voiceReferencePath = v;
              updateDirty();
            },
          }),
        ),
      ),
    );
    settingsCard.classList.add("col-6");

    // ── Возможности реализации ──────────────────────────────────
    const caps = base.capabilities;
    const capsCard = card(
      "Возможности реализации",
      h(
        "div",
        { class: "pill-row" },
        badge(`запись референса: ${caps.recordReference ? "есть" : "нет"}`, caps.recordReference ? "ok" : "warn"),
        badge(`PocketTTS: ${caps.pocketCloning ? "есть" : "нет"}`, caps.pocketCloning ? "ok" : "warn"),
        badge(`скорость речи: ${caps.speechSpeedConfig ? "задаётся" : "фиксирована"}`, caps.speechSpeedConfig ? "ok" : "warn"),
        badge(`громкость сразу: ${caps.liveVolumeApply ? "да" : "нет"}`, caps.liveVolumeApply ? "ok" : "warn"),
        badge(`микрофон (STT): ${caps.sttTest ? "доступен" : "нет"}`, caps.sttTest ? "ok" : "warn"),
      ),
      h("p", {
        class: "panel-note",
        text: "Значения честные для текущей реализации: C# умеет больше, "
          + "Python-порт отдаёт false там, где функции ещё нет — панель это показывает, "
          + "а не скрывает.",
      }),
      keyValue([
        { key: "Референс", value: base.voiceReferencePath || "—" },
        { key: "Движок", value: base.ttsEngine },
      ]),
    );
    capsCard.classList.add("col-6");

    // ── Тесты ────────────────────────────────────────────────────
    let testText = "Проверка голоса. Привет!";

    const testInput = textInput({
      value: testText,
      placeholder: "Фраза для озвучки (до 500 символов)",
      onInput: (v) => {
        testText = v;
      },
    });

    const speakBtn = button("Озвучить", () => void speak(), "primary");

    const recordBtn = button("Записать референс (15 с)", () => void recordReference(), "default");
    recordBtn.disabled = !caps.recordReference;
    if (!caps.recordReference) recordBtn.title = "Эта реализация не записывает референс (capabilities.recordReference=false)";

    const listenBtn = button("Тест микрофона", () => void listen());
    listenBtn.disabled = !caps.sttTest;
    if (!caps.sttTest) listenBtn.title = "STT сейчас недоступен (capabilities.sttTest=false)";

    async function speak(): Promise<void> {
      testErrorBox.hidden = true;

      const text = testText.trim();
      if (!text) {
        testErrorBox.textContent = "Введите фразу для озвучки.";
        testErrorBox.hidden = false;
        return;
      }
      if (text.length > MAX_TEST_TEXT) {
        testErrorBox.textContent = `Фраза длиннее ${MAX_TEST_TEXT} символов.`;
        testErrorBox.hidden = false;
        return;
      }

      speakBtn.disabled = true;

      try {
        await apiPost<{ status: "ok" }>("/api/voice/test", { text });

        if (cancelled) return;

        toast("Фраза озвучена", "ok");
        logEvent(`Тест озвучки: «${text.slice(0, 40)}»`);
      } catch (error) {
        if (cancelled) return;

        const message = error instanceof ApiError ? error.message : "Неизвестная ошибка";
        testErrorBox.textContent = message;
        testErrorBox.hidden = false;
        toast("Тест озвучки не удался", "danger");
        logEvent(`Ошибка теста озвучки: ${message}`);
      } finally {
        if (!cancelled) speakBtn.disabled = false;
      }
    }

    async function recordReference(): Promise<void> {
      testErrorBox.hidden = true;

      const confirmed = await confirmDialog({
        title: "Записать референс голоса?",
        message: "Микрофон запишет 15 секунд вашей речи для клонирования голоса. Говорите чётко и без шума.",
        confirmLabel: "Начать запись",
      });

      if (!confirmed) {
        toast("Запись референса отменена", "plain");
        logEvent("Запись референса отклонена пользователем");
        return;
      }

      recordBtn.disabled = true;

      try {
        const result = await apiPost<{ voiceReferencePath: string }>("/api/voice/reference", {});

        if (cancelled) return;

        base = { ...base, voiceReferencePath: result.voiceReferencePath };
        toast("Референс записан и сохранён в конфигурации", "ok");
        logEvent(`Референс голоса записан: ${result.voiceReferencePath}`);
        render(base, toDraft(base));
      } catch (error) {
        if (cancelled) return;

        const message = error instanceof ApiError ? error.message : "Неизвестная ошибка";
        testErrorBox.textContent = message;
        testErrorBox.hidden = false;
        toast("Запись референса не удалась", "danger");
        logEvent(`Ошибка записи референса: ${message}`);
        recordBtn.disabled = !caps.recordReference;
      }
    }

    async function listen(): Promise<void> {
      testErrorBox.hidden = true;
      testResult.hidden = true;

      listenBtn.disabled = true;

      try {
        const result = await apiPost<{ text: string }>("/api/voice/listen", {});

        if (cancelled) return;

        testResult.textContent = result.text
          ? `Распознано: «${result.text}»`
          : "Микрофон ничего не распознал.";
        testResult.hidden = false;
        toast("Распознавание выполнено", "ok");
        logEvent(`Тест микрофона: «${result.text.slice(0, 60)}»`);
      } catch (error) {
        if (cancelled) return;

        const message = error instanceof ApiError ? error.message : "Неизвестная ошибка";
        testErrorBox.textContent = message;
        testErrorBox.hidden = false;
        toast("Тест микрофона не удался", "danger");
        logEvent(`Ошибка теста микрофона: ${message}`);
      } finally {
        if (!cancelled) listenBtn.disabled = !caps.sttTest;
      }
    }

    const testCard = card(
      "Тестирование",
      h(
        "div",
        { class: "form-grid form-grid--single" },
        field("Фраза для озвучки", testInput, "Синтез через активный движок; 503 — TTS не инициализирован"),
        h("div", { class: "row-actions" }, speakBtn, recordBtn, listenBtn),
        testErrorBox,
        testResult,
      ),
    );
    testCard.classList.add("col-12");

    // ── Сборка ───────────────────────────────────────────────────
    container.append(
      pageHeader(
        "Голос",
        "Настройки voiceVolume/ttsEngine/… через POST /api/voice; тесты ходят в живой VoiceManager",
        [revertBtn, saveBtn],
      ),
      errorBox,
    );

    const grid = h("div", { class: "grid-12 fade-in" });
    grid.appendChild(settingsCard);
    grid.appendChild(capsCard);
    grid.appendChild(testCard);
    container.appendChild(grid);

    updateDirty();
  }

  void load();

  return () => {
    cancelled = true;
  };
};
