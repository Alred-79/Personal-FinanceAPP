import "@testing-library/jest-dom";
import { vi } from "vitest";
import { createElement, type ReactNode } from "react";

// Recharts requires ResizeObserver
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
vi.stubGlobal("ResizeObserver", ResizeObserverStub);

// matchMedia stub
Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
});

// IntersectionObserver stub
class IntersectionObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
vi.stubGlobal("IntersectionObserver", IntersectionObserverStub);

// Recharts' ResponsiveContainer measures its parent with ResizeObserver, which
// reports 0×0 in jsdom — so charts never render an <svg>. Force a fixed size so
// chart assertions work in tests. (Real layout is unaffected in the browser.)
vi.mock("recharts", async () => {
  const actual = await vi.importActual<typeof import("recharts")>("recharts");
  const Container = actual.ResponsiveContainer as unknown as (
    props: Record<string, unknown>
  ) => ReactNode;
  const Fixed = ({ children }: { children: ReactNode }) =>
    createElement(Container, { width: 600, height: 300 }, children);
  return { ...actual, ResponsiveContainer: Fixed };
});
