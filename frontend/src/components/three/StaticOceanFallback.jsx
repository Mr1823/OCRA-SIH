import './StaticOceanFallback.css';

/**
 * Zero-JS, zero-WebGL fallback hero background — used when the visitor
 * has prefers-reduced-motion set, the device has no WebGL, or the 3D
 * bundle fails to load for any reason. A gentle CSS gradient with a
 * faint wave pattern, no motion.
 */
export default function StaticOceanFallback() {
  return <div className="static-ocean-fallback" aria-hidden="true" />;
}
