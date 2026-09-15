import { Component } from 'react';

/**
 * Catches any runtime failure inside the lazy-loaded Three.js tree
 * (e.g. WebGL context creation failing on an unsupported device) and
 * falls back to the static hero instead of taking the whole landing
 * page down.
 */
export default class CanvasErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  componentDidCatch(error) {
    console.warn('ORCA: 3D ocean hero failed, falling back to static hero.', error);
  }

  render() {
    if (this.state.hasError) {
      return this.props.fallback;
    }
    return this.props.children;
  }
}
