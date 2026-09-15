import { useMemo, useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import * as THREE from 'three';

const VERTEX_SHADER = /* glsl */ `
  uniform float uTime;
  varying float vElevation;

  void main() {
    vec3 pos = position;
    float elevation =
      sin(pos.x * 0.4 + uTime * 0.6) * 0.22 +
      sin(pos.y * 0.3 - uTime * 0.45) * 0.32 +
      sin((pos.x + pos.y) * 0.15 + uTime * 0.28) * 0.38;
    pos.z += elevation;
    vElevation = elevation;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(pos, 1.0);
  }
`;

const FRAGMENT_SHADER = /* glsl */ `
  uniform vec3 uColorDeep;
  uniform vec3 uColorShallow;
  varying float vElevation;

  void main() {
    float mixFactor = smoothstep(-0.55, 0.65, vElevation);
    vec3 color = mix(uColorDeep, uColorShallow, mixFactor);
    gl_FragColor = vec4(color, 1.0);
  }
`;

/**
 * Stylized animated ocean surface — a displaced plane driven by layered
 * sine waves in the vertex shader, colored by wave height. Deliberately
 * simple (no lighting model, no reflections) to stay cheap on the GPU.
 */
export default function WavePlane() {
  const materialRef = useRef(null);

  const uniforms = useMemo(
    () => ({
      uTime: { value: 0 },
      uColorDeep: { value: new THREE.Color('#0a1628') },
      uColorShallow: { value: new THREE.Color('#22d3ee') },
    }),
    [],
  );

  useFrame((_, delta) => {
    if (materialRef.current) {
      materialRef.current.uniforms.uTime.value += delta;
    }
  });

  return (
    <mesh rotation={[-Math.PI / 2.6, 0, 0]} position={[0, -0.6, 0]}>
      <planeGeometry args={[18, 14, 128, 96]} />
      <shaderMaterial
        ref={materialRef}
        vertexShader={VERTEX_SHADER}
        fragmentShader={FRAGMENT_SHADER}
        uniforms={uniforms}
      />
    </mesh>
  );
}
