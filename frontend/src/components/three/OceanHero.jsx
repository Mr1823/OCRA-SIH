import { lazy, Suspense, useEffect, useState } from 'react';
import CanvasErrorBoundary from './CanvasErrorBoundary';
import StaticOceanFallback from './StaticOceanFallback';
import './OceanHero.css';

// Three.js is only fetched when this actually resolves — kept out of
// the initial bundle so the landing page's first paint never waits on it.
const OceanCanvas = lazy(() => import('./OceanCanvas'));

function prefersReducedMotion() {
  return (
    typeof window !== 'undefined' &&
    window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
  );
}

function hasWebGL() {
  if (typeof window === 'undefined') return false;
  try {
    const canvas = document.createElement('canvas');
    return !!(
      window.WebGLRenderingContext &&
      (canvas.getContext('webgl') || canvas.getContext('experimental-webgl'))
    );
  } catch {
    return false;
  }
}

/**
 * Hero background: an animated shader ocean plane when the device and
 * user preferences allow it, otherwise a static gradient — degrades
 * gracefully rather than forcing 3D on everyone.
 */
export default function OceanHero() {
  const [canRender3D, setCanRender3D] = useState(false);

  useEffect(() => {
    setCanRender3D(!prefersReducedMotion() && hasWebGL());
  }, []);

  return (
    <div className="ocean-hero">
      {canRender3D ? (
        <CanvasErrorBoundary fallback={<StaticOceanFallback />}>
          <Suspense fallback={<StaticOceanFallback />}>
            <OceanCanvas />
          </Suspense>
        </CanvasErrorBoundary>
      ) : (
        <StaticOceanFallback />
      )}
    </div>
  );
}
