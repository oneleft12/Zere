/** Заглушки экранов, которые подключаются на этапах 3–4 плана. */

import { emptyState, pageHeader } from "../ui";
import type { ScreenFactory } from "../router";

export function futureScreen(title: string, stage: number): ScreenFactory {
  return (container) => {
    container.appendChild(
      pageHeader(title, `Планируется на этапе ${stage} плана разработки GUI`),
    );
    container.appendChild(
      emptyState({
        icon: "🚧",
        title: `Экран «${title}» пока не реализован`,
        hint: `Он появится на этапе ${stage}: контрактные эндпоинты и UI-часть строятся по docs/GUI_DEVELOPMENT_PLAN.md.`,
      }),
    );
  };
}
