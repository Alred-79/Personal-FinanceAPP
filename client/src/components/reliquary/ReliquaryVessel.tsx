import { useRef } from "react";
import { useFrame, ThreeEvent } from "@react-three/fiber";
import { Group, MathUtils, DoubleSide } from "three";
import type { Goal } from "@/store/store";
import { FillColumn } from "./FillColumn";
import { VesselLabel } from "./VesselLabel";
import { useReliquaryStore } from "./useReliquaryStore";
import { ReliquaryColors } from "./useReliquaryColors";

const BODY_H = 1.5;
const RADIUS = 0.42;

/** One reliquary phial: glass body, gold foot/neck/cap, and the earmark-banded
 *  fill. Hover/select lift is a ref lerp in useFrame (no setState in frame). */
export function ReliquaryVessel({
  goal,
  position,
  colors,
  reduce,
  onSelect,
}: {
  goal: Goal;
  position: [number, number, number];
  colors: ReliquaryColors;
  reduce: boolean;
  onSelect: (goal: Goal) => void;
}) {
  const group = useRef<Group>(null);
  const id = goal.id ?? -1;
  const setHovered = useReliquaryStore((s) => s.setHovered);

  useFrame(() => {
    if (!group.current) return;
    const { hoveredId, selectedId } = useReliquaryStore.getState();
    const active = hoveredId === id || selectedId === id;
    const targetY = position[1] + (active && !reduce ? 0.14 : 0);
    group.current.position.y = MathUtils.lerp(
      group.current.position.y,
      targetY,
      0.15
    );
  });

  const over = (e: ThreeEvent<PointerEvent>) => {
    e.stopPropagation();
    setHovered(id);
    document.body.style.cursor = "pointer";
  };
  const out = (e: ThreeEvent<PointerEvent>) => {
    e.stopPropagation();
    setHovered(null);
    document.body.style.cursor = "auto";
  };

  return (
    <group
      ref={group}
      position={position}
      onPointerOver={over}
      onPointerOut={out}
      onClick={(e) => {
        e.stopPropagation();
        onSelect(goal);
      }}
    >
      {/* foot */}
      <mesh position={[0, -BODY_H / 2 - 0.09, 0]}>
        <cylinderGeometry args={[RADIUS * 0.82, RADIUS * 0.96, 0.18, 28]} />
        <meshStandardMaterial color={colors.gold} metalness={0.6} roughness={0.45} />
      </mesh>

      {/* liquid + earmark strata (drawn before the glass) */}
      <FillColumn
        progress={goal.progress ?? 0}
        amount={goal.amount}
        earmarks={goal.earmarks ?? []}
        colors={colors}
        bodyH={BODY_H}
        radius={RADIUS}
      />

      {/* glass body */}
      <mesh>
        <cylinderGeometry args={[RADIUS, RADIUS, BODY_H, 36, 1, true]} />
        <meshStandardMaterial
          color={colors.glass}
          transparent
          opacity={0.22}
          roughness={0.12}
          metalness={0}
          side={DoubleSide}
        />
      </mesh>

      {/* neck */}
      <mesh position={[0, BODY_H / 2 + 0.06, 0]}>
        <cylinderGeometry args={[RADIUS * 0.45, RADIUS * 0.72, 0.18, 24, 1, true]} />
        <meshStandardMaterial
          color={colors.glass}
          transparent
          opacity={0.25}
          roughness={0.12}
          side={DoubleSide}
        />
      </mesh>

      {/* gold stopper cap */}
      <mesh position={[0, BODY_H / 2 + 0.18, 0]}>
        <cylinderGeometry args={[RADIUS * 0.5, RADIUS * 0.5, 0.13, 24]} />
        <meshStandardMaterial color={colors.gold} metalness={0.6} roughness={0.4} />
      </mesh>

      <VesselLabel
        name={goal.name}
        progress={goal.progress ?? 0}
        amount={goal.amount}
        y={-BODY_H / 2 - 0.62}
      />
    </group>
  );
}
