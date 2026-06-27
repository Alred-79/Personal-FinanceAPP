import { useAnimations, useGLTF } from "@react-three/drei";
import { useFrame } from "@react-three/fiber";
import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import { clone as skeletonClone } from "three/examples/jsm/utils/SkeletonUtils.js";

const URL = "/models/debt-beast.glb";
useGLTF.preload(URL);

export type BeastPhase = "idle" | "hit" | "dead";

/** Inject a noise dissolve into a standard material: as `uHealth` falls the beast
 *  corrodes from the edges, with a molten-gold rim glowing at the dissolve front.
 *  Returns the uniform we drive each frame. */
function makeDissolve(mat: THREE.MeshStandardMaterial) {
  const uHealth = { value: 1 };
  mat.onBeforeCompile = (shader) => {
    shader.uniforms.uHealth = uHealth;
    shader.uniforms.uEdge = { value: 0.08 };
    shader.uniforms.uScale = { value: 2.6 };
    shader.vertexShader =
      "varying vec3 vDis;\n" +
      shader.vertexShader.replace("#include <begin_vertex>", "#include <begin_vertex>\n vDis = position;");
    shader.fragmentShader =
      `
      uniform float uHealth; uniform float uEdge; uniform float uScale;
      varying vec3 vDis;
      float h31(vec3 p){ p=fract(p*0.3183099+0.1); p*=17.0; return fract(p.x*p.y*p.z*(p.x+p.y+p.z)); }
      float n31(vec3 x){ vec3 i=floor(x),f=fract(x); f=f*f*(3.0-2.0*f);
        return mix(mix(mix(h31(i+vec3(0,0,0)),h31(i+vec3(1,0,0)),f.x),mix(h31(i+vec3(0,1,0)),h31(i+vec3(1,1,0)),f.x),f.y),
                   mix(mix(h31(i+vec3(0,0,1)),h31(i+vec3(1,0,1)),f.x),mix(h31(i+vec3(0,1,1)),h31(i+vec3(1,1,1)),f.x),f.y),f.z); }
      ` + shader.fragmentShader;
    shader.fragmentShader = shader.fragmentShader.replace(
      "#include <dithering_fragment>",
      `
      float dN = n31(vDis * uScale) * 0.7 + n31(vDis * uScale * 2.7) * 0.3;
      float thr = 1.0 - uHealth;
      if (dN < thr) discard;
      float e = smoothstep(thr, thr + uEdge, dN);
      vec3 molten = mix(vec3(1.0, 0.28, 0.12), vec3(1.0, 0.66, 0.18), uHealth);
      gl_FragColor.rgb += (1.0 - e) * molten * 2.4;
      #include <dithering_fragment>
      `
    );
  };
  mat.needsUpdate = true;
  return uHealth;
}

/**
 * The debt-beast — a CC0 Quaternius "Giant" rig (public/models/debt-beast.glb),
 * re-skinned into minted gold/bronze metal. `health` (1→0) drives it: the body
 * corrodes via a dissolve shader, the metal drains warm→ash, it sinks and slows,
 * molten cracks glow brighter as it weakens. A strike plays HitRecieve; defeat
 * plays Death. The numbers/logic live in React above; this is pure spectacle.
 */
export function BeastModel({ health, phase, hitKey }: { health: number; phase: BeastPhase; hitKey: number }) {
  const group = useRef<THREE.Group>(null);
  const { scene, animations } = useGLTF(URL);
  const cloned = useMemo(() => skeletonClone(scene), [scene]);
  const { actions, names } = useAnimations(animations, group);

  // shown health lags the target so changes ease in; mutated in useFrame (no state)
  const shown = useRef(1);
  const dissolves = useRef<{ value: number }[]>([]);
  // The beast's resting y — MUST match the group's JSX position below (feet on the
  // contact shadow at ~-1.16). useFrame drives position.y from this every frame, so
  // if it were 0 the model would snap up ~1.15u on the first frame and only its feet
  // would stay in frame (the "can't see the boss" bug).
  const baseY = useRef(-1.15);

  // re-skin to gold metal + wire the dissolve once per clone
  useMemo(() => {
    const us: { value: number }[] = [];
    cloned.traverse((o) => {
      const m = o as THREE.Mesh;
      if (!m.isMesh) return;
      m.castShadow = m.receiveShadow = false;
      const gold = new THREE.MeshStandardMaterial({
        color: new THREE.Color("#caa24a"),
        metalness: 0.92,
        roughness: 0.32,
        emissive: new THREE.Color("#3a1d08"),
        emissiveIntensity: 0.4,
        envMapIntensity: 1.4,
      });
      us.push(makeDissolve(gold));
      m.material = gold;
    });
    dissolves.current = us;
  }, [cloned]);

  const clip = (needle: string) => names.find((n) => n.toLowerCase().includes(needle));

  // idle loop on mount
  useEffect(() => {
    const idle = clip("idle");
    if (idle && actions[idle]) actions[idle].reset().fadeIn(0.3).play();
    return () => {
      const i = clip("idle");
      if (i && actions[i]) actions[i].fadeOut(0.2);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [actions, names]);

  // a strike → play HitRecieve once, then settle back to idle
  useEffect(() => {
    if (hitKey === 0 || phase === "dead") return;
    const hit = clip("hitrecieve") || clip("hit");
    const idle = clip("idle");
    if (hit && actions[hit]) {
      const a = actions[hit];
      a.reset();
      a.setLoop(THREE.LoopOnce, 1);
      a.clampWhenFinished = false;
      a.fadeIn(0.05).play();
      if (idle && actions[idle]) actions[idle].crossFadeFrom(a, 0.0, false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hitKey]);

  // defeat → Death, clamped
  useEffect(() => {
    if (phase !== "dead") return;
    const death = clip("death");
    if (death && actions[death]) {
      const a = actions[death];
      a.reset();
      a.setLoop(THREE.LoopOnce, 1);
      a.clampWhenFinished = true;
      a.fadeIn(0.1).play();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase]);

  useFrame((_, dt) => {
    const g = group.current;
    if (!g) return;
    const k = 1 - Math.pow(0.001, dt); // frame-rate-independent ease
    shown.current += (health - shown.current) * k;
    const h = shown.current;
    const d = 1 - h;
    for (const u of dissolves.current) u.value = h;
    // sink + list to the side as it weakens; slow idle sway
    g.position.y = baseY.current - d * 0.5;
    g.rotation.z = -d * 0.18;
    g.rotation.y += dt * (0.25 * h + 0.04); // turns slower as it dies
  });

  return (
    <group ref={group} position={[0, -1.15, 0]} scale={1.15} dispose={null}>
      <primitive object={cloned} />
    </group>
  );
}
