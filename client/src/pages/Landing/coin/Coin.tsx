import { useEffect, useMemo, useRef } from "react";
import { useFrame, useThree } from "@react-three/fiber";
import { CanvasTexture, Group, MathUtils, RepeatWrapping } from "three";
import { makeCoinFaceCanvas, makeReedCanvas, type CoinSide } from "./coinFace";

const FACE_BUMP = 0.085;
/** Pointer travel (px) under which a press counts as a tap-to-flip, not a drag. */
const TAP_SLOP = 5;

const parity = (spin: number) => ((Math.round(spin / Math.PI) % 2) + 2) % 2;
const sideOf = (n: number): CoinSide => (n === 0 ? "balance" : "safe");

/**
 * The struck two-sided coin: "what your bank says" on the front cap, "safe to
 * spend" on the back. Drag to spin, tap to flip; on release it settles on the
 * nearer face (a flick carries through to the other side). The parent can also
 * request a side (`side`), and hears which side is facing the camera
 * (`onSideChange`) so the ledger beside it can follow along. All motion lives on
 * refs and is mutated in useFrame — never setState per frame.
 */
export function Coin({
  side,
  onSideChange,
}: {
  side: CoinSide;
  onSideChange?: (side: CoinSide) => void;
}) {
  const group = useRef<Group>(null);
  const { gl } = useThree();
  // spin: the flip rotation about Y, easing toward `target` (a multiple of PI).
  // tilt: a drag-applied X offset that eases back to the idle wobble.
  const drag = useRef({
    active: false,
    spin: 0,
    target: side === "safe" ? Math.PI : 0,
    tilt: 0,
    vy: 0,
    lastX: 0,
    lastY: 0,
    travel: 0,
    // spin starts at 0 (the bank's side). Only real crossings are reported, so a
    // late-loading scene can't overwrite a side the page already asked for.
    facing: "balance" as CoinSide,
  });
  const onSideRef = useRef(onSideChange);
  onSideRef.current = onSideChange;

  const balanceTex = useMemo(() => {
    const t = new CanvasTexture(makeCoinFaceCanvas(1024, "balance"));
    t.anisotropy = 4;
    return t;
  }, []);
  const safeTex = useMemo(() => {
    const t = new CanvasTexture(makeCoinFaceCanvas(1024, "safe"));
    t.anisotropy = 4;
    return t;
  }, []);
  const reedTex = useMemo(() => {
    const t = new CanvasTexture(makeReedCanvas(1024, 64));
    t.wrapS = t.wrapT = RepeatWrapping;
    return t;
  }, []);

  useEffect(() => {
    return () => {
      balanceTex.dispose();
      safeTex.dispose();
      reedTex.dispose();
    };
  }, [balanceTex, safeTex, reedTex]);

  // A requested side the coin isn't already settling on turns it over.
  useEffect(() => {
    const d = drag.current;
    if (sideOf(parity(d.target)) !== side) d.target += Math.PI;
  }, [side]);

  // Pointer drag: down on the canvas, move/up on the window so the gesture
  // continues even when the pointer leaves the coin.
  useEffect(() => {
    const el = gl.domElement;
    const d = drag.current;
    const k = 0.009;
    const down = (e: PointerEvent) => {
      d.active = true;
      d.lastX = e.clientX;
      d.lastY = e.clientY;
      d.travel = 0;
      d.vy = 0;
      el.style.cursor = "grabbing";
    };
    const move = (e: PointerEvent) => {
      if (!d.active) return;
      const dx = e.clientX - d.lastX;
      const dy = e.clientY - d.lastY;
      d.lastX = e.clientX;
      d.lastY = e.clientY;
      d.travel += Math.abs(dx) + Math.abs(dy);
      d.spin += dx * k;
      d.tilt += dy * k;
      d.vy = dx * k;
    };
    const up = () => {
      if (!d.active) return;
      d.active = false;
      el.style.cursor = "grab";
      if (d.travel < TAP_SLOP) {
        d.target = Math.round(d.spin / Math.PI) * Math.PI + Math.PI;
      } else {
        // Project the release velocity forward so a flick carries over.
        d.target = Math.round((d.spin + d.vy * 14) / Math.PI) * Math.PI;
      }
    };
    el.style.cursor = "grab";
    el.style.touchAction = "none";
    el.addEventListener("pointerdown", down);
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    return () => {
      el.removeEventListener("pointerdown", down);
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
  }, [gl]);

  useFrame((state, delta) => {
    const g = group.current;
    if (!g) return;
    const d = drag.current;
    if (!d.active) {
      // frame-rate independent ease toward the settled face; tilt back to idle
      const ease = 1 - Math.pow(0.004, Math.min(delta, 0.1));
      d.spin += (d.target - d.spin) * ease;
      d.tilt *= 1 - ease;
    }
    const t = state.clock.elapsedTime;
    // layered, multi-axis float; its Y swing stays well under PI/2, so the idle
    // wobble alone never shows the other face
    const baseY = Math.sin(t * 0.32) * 0.5 + Math.sin(t * 0.11 + 1.3) * 0.3;
    const baseX = Math.sin(t * 0.27) * 0.22 + Math.sin(t * 0.19) * 0.08;
    const baseZ = Math.sin(t * 0.16) * 0.12;
    g.rotation.y = baseY + d.spin;
    g.rotation.x = MathUtils.clamp(baseX + d.tilt, -0.75, 0.75);
    g.rotation.z = baseZ;
    g.position.y = Math.sin(t * 0.6) * 0.06;
    g.position.x = Math.sin(t * 0.44 + 2.0) * 0.04;

    const facing: CoinSide =
      Math.cos(g.rotation.y) * Math.cos(g.rotation.x) >= 0 ? "balance" : "safe";
    if (facing !== d.facing) {
      d.facing = facing;
      onSideRef.current?.(facing);
    }
  });

  const face = (map: CanvasTexture) => ({
    color: "#d8a93e",
    metalness: 1,
    roughness: 0.3,
    clearcoat: 0.5,
    clearcoatRoughness: 0.28,
    bumpMap: map,
    bumpScale: FACE_BUMP,
    roughnessMap: map,
    envMapIntensity: 1.5,
  });

  return (
    <group ref={group}>
      <mesh rotation={[Math.PI / 2, 0, 0]}>
        <cylinderGeometry args={[1.3, 1.3, 0.17, 120, 1, false]} />
        <meshPhysicalMaterial
          attach="material-0"
          color="#c89a36"
          metalness={1}
          roughness={0.4}
          clearcoat={0.35}
          clearcoatRoughness={0.35}
          bumpMap={reedTex}
          bumpScale={0.03}
          envMapIntensity={1.35}
        />
        {/* top cap faces the camera at rest: the bank's side */}
        <meshPhysicalMaterial attach="material-1" {...face(balanceTex)} />
        {/* bottom cap, seen once turned over: the safe-to-spend side */}
        <meshPhysicalMaterial attach="material-2" {...face(safeTex)} />
      </mesh>
    </group>
  );
}
