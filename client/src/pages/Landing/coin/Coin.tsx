import { useEffect, useMemo, useRef } from "react";
import { useFrame, useThree } from "@react-three/fiber";
import { CanvasTexture, Group, MathUtils, RepeatWrapping } from "three";
import { makeCoinFaceCanvas, makeReedCanvas } from "./coinFace";

const FACE_BUMP = 0.06;

/**
 * The struck "Good Standing" sovereign. A gold cylinder with an engraved face
 * (bump + roughness from a canvas relief) and a milled edge. Drag to spin — the
 * rotation lives entirely on a ref and is mutated in useFrame (never setState),
 * with inertia + a gentle idle turn and float when released.
 */
export function Coin() {
  const group = useRef<Group>(null);
  const { gl } = useThree();
  // dragY/dragX are user-applied spin offsets that decay back toward the idle
  // face-forward wobble; vy/vx carry release inertia.
  const drag = useRef({
    active: false,
    dragY: 0,
    dragX: 0,
    vy: 0,
    vx: 0,
    lastX: 0,
    lastY: 0,
  });

  const faceTex = useMemo(() => {
    const t = new CanvasTexture(makeCoinFaceCanvas(1024));
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
      faceTex.dispose();
      reedTex.dispose();
    };
  }, [faceTex, reedTex]);

  // Pointer drag: down on the canvas, move/up on the window so the gesture
  // continues even when the pointer leaves the coin.
  useEffect(() => {
    const el = gl.domElement;
    const d = drag.current;
    const down = (e: PointerEvent) => {
      d.active = true;
      d.lastX = e.clientX;
      d.lastY = e.clientY;
      d.vy = 0;
      d.vx = 0;
      el.style.cursor = "grabbing";
    };
    const move = (e: PointerEvent) => {
      if (!d.active) return;
      const dx = e.clientX - d.lastX;
      const dy = e.clientY - d.lastY;
      d.lastX = e.clientX;
      d.lastY = e.clientY;
      const k = 0.009;
      d.dragY += dx * k;
      d.dragX += dy * k;
      d.vy = dx * k;
      d.vx = dy * k;
    };
    const up = () => {
      d.active = false;
      el.style.cursor = "grab";
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

  useFrame((state) => {
    const g = group.current;
    if (!g) return;
    const d = drag.current;
    if (!d.active) {
      // release inertia, then decay the spin offset back to the idle wobble
      d.dragY += d.vy;
      d.dragX += d.vx;
      d.vy *= 0.94;
      d.vx *= 0.94;
      d.dragY *= 0.96;
      d.dragX *= 0.96;
    }
    const t = state.clock.elapsedTime;
    // layered, multi-axis float — explores more angles without a mechanical loop
    const baseY = Math.sin(t * 0.32) * 0.7 + Math.sin(t * 0.11 + 1.3) * 0.45;
    const baseX = Math.sin(t * 0.27) * 0.26 + Math.sin(t * 0.19) * 0.1;
    const baseZ = Math.sin(t * 0.16) * 0.13;
    g.rotation.y = baseY + d.dragY;
    g.rotation.x = MathUtils.clamp(baseX + d.dragX, -0.75, 0.75);
    g.rotation.z = baseZ;
    g.position.y = Math.sin(t * 0.6) * 0.06;
    g.position.x = Math.sin(t * 0.44 + 2.0) * 0.04;
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
        <meshPhysicalMaterial
          attach="material-1"
          color="#d8a93e"
          metalness={1}
          roughness={0.3}
          clearcoat={0.5}
          clearcoatRoughness={0.28}
          bumpMap={faceTex}
          bumpScale={FACE_BUMP}
          roughnessMap={faceTex}
          envMapIntensity={1.5}
        />
        <meshPhysicalMaterial
          attach="material-2"
          color="#d8a93e"
          metalness={1}
          roughness={0.3}
          clearcoat={0.5}
          clearcoatRoughness={0.28}
          bumpMap={faceTex}
          bumpScale={FACE_BUMP}
          roughnessMap={faceTex}
          envMapIntensity={1.5}
        />
      </mesh>
    </group>
  );
}
