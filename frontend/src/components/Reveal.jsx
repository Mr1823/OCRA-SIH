import useReveal from '../hooks/useReveal';

/**
 * Wraps children in a fade/slide-up-on-scroll effect. A thin
 * presentational wrapper around useReveal so section markup in
 * Landing.jsx stays declarative.
 */
export default function Reveal({ as: Tag = 'div', className = '', delay = 0, children, ...rest }) {
  const [ref, visible] = useReveal();

  return (
    <Tag
      ref={ref}
      className={`reveal ${visible ? 'reveal-visible' : ''} ${className}`.trim()}
      style={{ transitionDelay: visible ? `${delay}ms` : '0ms' }}
      {...rest}
    >
      {children}
    </Tag>
  );
}
