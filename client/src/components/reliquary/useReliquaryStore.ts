import { create } from "zustand";

/**
 * Selection/hover state for the Reliquary, in its own tiny store so `useFrame`
 * loops read it via `getState()` without subscribing (no re-render churn, no
 * setState-in-frame). Per r3f-best-practices: zustand selectors over prop-drill.
 */
interface ReliquaryState {
  selectedId: number | null;
  hoveredId: number | null;
  setSelected: (id: number | null) => void;
  setHovered: (id: number | null) => void;
}

export const useReliquaryStore = create<ReliquaryState>((set) => ({
  selectedId: null,
  hoveredId: null,
  setSelected: (id) => set({ selectedId: id }),
  setHovered: (id) => set({ hoveredId: id }),
}));
