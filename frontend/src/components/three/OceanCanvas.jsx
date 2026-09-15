import { Canvas } from '@react-three/fiber';
import WavePlane from './WavePlane';

/**
 * The actual Three.js scene — isolated into its own module so it can be
 * loaded via React.lazy() and kept out of the initial JS bundle. Never
 * import this directly outside of OceanHero's lazy() call.
 */
export default function OceanCanvas() {
  return (
    <Canvas
      dpr={[1, 1.5]}
      camera={{ position: [0, 2.4, 7.5], fov: 45 }}
      gl={{ antialias: true, alpha: true, powerPreference: 'low-power' }}
    >
      <color attach="background" args={['#0a1628']} />
      <fog attach="fog" args={['#0a1628', 6, 14]} />
      <WavePlane />
    </Canvas>
  );
}
