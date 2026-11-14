import "@testing-library/jest-dom/vitest";
import { cleanup, configure } from "@testing-library/react";
import { afterEach, vi } from "vitest";
import { setLanguage } from "../i18n";
import { resetLiveHub } from "../lib/liveHub";

// findBy*/waitFor czekają do 3 s zamiast 1 s: pierwszy test w pliku ładuje moduły panelu na żądanie i na obciążonym
// serwerze CI trwało to czasem ponad sekundę (Wan.test.tsx „Teraz: LTE”, 1160 ms – test przechodził po ponowieniu).
configure({ asyncUtilTimeout: 3000 });

// Testy sprawdzają polskie teksty – niezależnie od języka środowiska (jsdom: en-US)
setLanguage("pl", { reload: false });

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  localStorage.clear();
  setLanguage("pl", { reload: false });
  resetLiveHub(); // wspólny kanał na żywo żyje w module – każdy test zaczyna bez połączeń
  delete document.documentElement.dataset.theme;
});

// jsdom nie ma ResizeObserver (siatka pulpitu mierzy nim szerokość; w testach zostaje szerokość początkowa 1280 px)
if (!("ResizeObserver" in window)) {
  class ResizeObserverStub {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  Object.defineProperty(window, "ResizeObserver", { writable: true, value: ResizeObserverStub });
}

// jsdom nie ma matchMedia
if (!window.matchMedia) {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    }),
  });
}

// jsdom nie ma canvasu, a wykresy ECharts go wymagają – w testach zastępuje je prosty stub:
// nazwy widocznych serii, osie i liczba punktów
vi.mock("../components/charts/PanelChart", () => ({
  default: ({ lines, ariaLabel, right }: { lines: { name: string; rows: unknown[] }[]; ariaLabel: string; right: unknown }) => (
    <div role="img" aria-label={ariaLabel} data-testid="chart" data-points={lines[0]?.rows.length ?? 0} data-right-axis={right ? "yes" : "no"}>
      {lines.map((l) => l.name).join(", ")}
    </div>
  ),
}));

