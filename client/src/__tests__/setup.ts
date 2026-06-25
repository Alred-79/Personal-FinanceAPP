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

// Radix UI primitives (Select, etc.) call these DOM methods that jsdom doesn't
// implement. Stub them so component tests that open a Select don't crash.
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = function scrollIntoView() {};
} else {
  Element.prototype.scrollIntoView = function scrollIntoView() {};
}
if (!Element.prototype.hasPointerCapture) {
  Element.prototype.hasPointerCapture = function hasPointerCapture() {
    return false;
  };
}
if (!Element.prototype.releasePointerCapture) {
  Element.prototype.releasePointerCapture = function releasePointerCapture() {};
}
if (!Element.prototype.setPointerCapture) {
  Element.prototype.setPointerCapture = function setPointerCapture() {};
}

// jsdom has no canvas backend, so getContext throws "Not implemented" and spams
// stderr. Canvas-based visuals (e.g. MoneyFlow's particle layer) guard on a null
// context and skip rendering, so stub it to return null for a clean, quiet run.
HTMLCanvasElement.prototype.getContext = function getContext() {
  return null;
} as typeof HTMLCanvasElement.prototype.getContext;

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
