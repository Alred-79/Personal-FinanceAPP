import { Canvas } from "@react-three/fiber";
import { ContactShadows, Environment } from "@react-three/drei";
import { Bloom, EffectComposer } from "@react-three/postprocessing";
import lobby from "@pmndrs/assets/hdri/lobby.exr";
import { BeastModel, type BeastPhase } from "./BeastModel";

/**
 * The debt-beast's 3D stage. A bundled HDRI gives the minted-gold metal real,
 * physically-grounded reflections; a warm rim light reads as forge-heat; bloom
 * makes the molten dissolve cracks glow. Transparent canvas so the beast floats
 * on the arcade screen. Default export for code-splitting.
 */
export default function BeastScene({
  health,
  phase,
  hitKey,
}: {
  health: number;
  phase: BeastPhase;
  hitKey: number;
}) {
  return (
    <Canvas
      camera={{ position: [0, 0.45, 4.4], fov: 32 }}
      dpr={[1, 2]}
      gl={{ alpha: true, antialias: true, toneMappingExposure: 1.1 }}
    >
      <BeastModel health={health} phase={phase} hitKey={hitKey} />
      <Environment files={lobby as string} resolution={256} />
      <directionalLight position={[4, 6, 5]} intensity={1.2} />
      <directionalLight position={[-4, 1, 2]} intensity={0.55} color="#ff9b5a" />
      <ContactShadows position={[0, -1.16, 0]} opacity={0.5} scale={6} blur={2.6} far={3} color="#2a0d04" />
      <EffectComposer>
        <Bloom intensity={0.85} luminanceThreshold={0.55} luminanceSmoothing={0.22} mipmapBlur />
      </EffectComposer>
    </Canvas>
  );
}
