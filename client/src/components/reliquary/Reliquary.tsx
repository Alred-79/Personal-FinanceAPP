import { Canvas } from "@react-three/fiber";
import { OrbitControls } from "@react-three/drei";
import { DoubleSide } from "three";
import type { Goal } from "@/store/store";
import { useReducedMotion } from "@/hooks/useEnvironment";
import { ReliquaryVessel } from "./ReliquaryVessel";
import { ReliquaryFocusPanel } from "./ReliquaryFocusPanel";
import { useReliquaryColors } from "./useReliquaryColors";
import { useReliquaryStore } from "./useReliquaryStore";

const SPACING = 1.45;

/**
 * The 3D goal vault. A shelf of phials, orbit-able, each click-selectable; the
 * selected one's detail lives in a DOM panel (color law). This module is the
 * ONLY entry into three/R3F, so the lazy boundary in ReliquaryLazy splits it —
 * and everything it imports — into an async chunk loaded only when shown.
 */
export default function Reliquary({
  goals,
  onEdit,
  onDeposit,
  onWhatIf,
}: {
  goals: Goal[];
  onEdit: (g: Goal) => void;
  onDeposit: (g: Goal) => void;
  onWhatIf: (g: Goal) => void;
}) {
  const colors = useReliquaryColors();
  const reduce = useReducedMotion();
  const selectedId = useReliquaryStore((s) => s.selectedId);
  const setSelected = useReliquaryStore((s) => s.setSelected);
  const selected = goals.find((g) => g.id === selectedId) ?? null;

  const n = goals.length;
  const shelfW = Math.max(4, n * SPACING + 1.6);

  return (
    <div className="relative h-[clamp(420px,60vh,560px)] w-full overflow-hidden border border-rule-strong/20 bg-card/40">
      <Canvas
        camera={{ position: [0, 1.1, 6.2], fov: 42 }}
        dpr={[1, 2]}
        gl={{ alpha: true, antialias: true }}
        onPointerMissed={() => setSelected(null)}
      >
        <ambientLight intensity={0.6} />
        <directionalLight position={[4, 6, 4]} intensity={1.1} />
        <directionalLight position={[-4, 2, -2]} intensity={0.3} />

        {/* the shelf */}
        <mesh position={[0, -1.0, 0]}>
          <boxGeometry args={[shelfW, 0.14, 1.7]} />
          <meshStandardMaterial
            color={colors.glass}
            metalness={0.2}
            roughness={0.7}
            transparent
            opacity={0.5}
            side={DoubleSide}
          />
        </mesh>

        {goals.map((g, i) => (
          <ReliquaryVessel
            key={g.id ?? i}
            goal={g}
            position={[(i - (n - 1) / 2) * SPACING, -0.05, 0]}
            colors={colors}
            reduce={reduce}
            onSelect={(goal) => setSelected(goal.id ?? null)}
          />
        ))}

        <OrbitControls
          enablePan={false}
          enableDamping
          minPolarAngle={Math.PI / 3}
          maxPolarAngle={Math.PI / 2.05}
          minDistance={4.5}
          maxDistance={9}
          autoRotate={!reduce && selectedId == null}
          autoRotateSpeed={0.5}
        />
      </Canvas>

      {selected && (
        <ReliquaryFocusPanel
          goal={selected}
          onClose={() => setSelected(null)}
          onEdit={onEdit}
          onDeposit={onDeposit}
          onWhatIf={onWhatIf}
        />
      )}
    </div>
  );
}
