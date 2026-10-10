import { Canvas } from "@react-three/fiber";
import { Environment } from "@react-three/drei";
import lobby from "@pmndrs/assets/hdri/lobby.exr";
import { Coin } from "./Coin";
import type { CoinSide } from "./coinFace";

/**
 * The coin's 3D stage. A real (bundled, no-network) HDRI gives the gold varied,
 * physically-grounded reflections — bright window glints AND darker interior
 * tones across the face, which is what reads as hyperrealistic metal and lets the
 * struck relief catch the light. Two directional lights add a sharp specular that
 * sweeps as the coin turns. No post-processing, so the canvas stays transparent
 * and the coin floats on the page. Default export for code-splitting.
 */
export default function CoinScene({
  side,
  onSideChange,
}: {
  side: CoinSide;
  onSideChange?: (side: CoinSide) => void;
}) {
  return (
    <Canvas
      camera={{ position: [0, 0, 5.3], fov: 34 }}
      dpr={[1, 2]}
      gl={{ alpha: true, antialias: true, toneMappingExposure: 1.15 }}
    >
      <Coin side={side} onSideChange={onSideChange} />
      <Environment files={lobby as string} resolution={256} />
      <directionalLight position={[4, 6, 5]} intensity={1.15} />
      <directionalLight position={[-3, -2, 4]} intensity={0.35} color="#ffdca8" />
    </Canvas>
  );
}
