/**
 * Small "Built with Understand Tech" badge pinned to the bottom-right
 * of every generated app. Same role as Lovable's "Built with Lovable"
 * badge: passive attribution that's visible on every page without
 * obstructing the user's app.
 *
 * Dismissable — users can click the close button to hide it for this
 * browser. Choice persists in localStorage. The badge re-appears in a
 * fresh browser / private window, which is fine for the attribution
 * intent (the end user got the choice; we don't nag them).
 *
 * Builder-internal: do not edit. The orchestrator mounts this as a
 * sibling of <App /> in `main.tsx` so it ships on every screen
 * regardless of routing.
 */
import { useState } from 'react';
import utLogo from './assets/ut-logo.svg';

const DISMISS_KEY = 'ut-builder.badge-dismissed';

export default function BuiltWithBadge() {
  const [dismissed, setDismissed] = useState<boolean>(() => {
    if (typeof window === 'undefined') return false;
    try {
      return window.localStorage.getItem(DISMISS_KEY) === '1';
    } catch {
      return false;
    }
  });

  if (dismissed) return null;

  const dismiss = (e: React.MouseEvent) => {
    // Stop the click from bubbling to the parent <a> and following the
    // link before we hide.
    e.preventDefault();
    e.stopPropagation();
    try {
      window.localStorage.setItem(DISMISS_KEY, '1');
    } catch {
      // localStorage unavailable (private mode / storage full) — still
      // hide for this session even if we can't persist the choice.
    }
    setDismissed(true);
  };

  return (
    <a
      href="https://understand.tech"
      target="_blank"
      rel="noopener noreferrer"
      aria-label="Built with Understand Tech"
      title="Built with Understand Tech"
      style={{
        position: 'fixed',
        right: '12px',
        bottom: '12px',
        zIndex: 99999,
        display: 'inline-flex',
        alignItems: 'center',
        gap: '6px',
        padding: '6px 8px 6px 10px',
        background: 'rgba(255, 255, 255, 0.92)',
        backdropFilter: 'blur(8px)',
        WebkitBackdropFilter: 'blur(8px)',
        border: '1px solid rgba(0, 0, 0, 0.08)',
        borderRadius: '999px',
        boxShadow: '0 1px 3px rgba(0, 0, 0, 0.08)',
        color: '#1f2328',
        fontSize: '11px',
        fontFamily:
          '-apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif',
        fontWeight: 500,
        textDecoration: 'none',
        letterSpacing: '-0.005em',
        transition: 'transform 140ms ease, box-shadow 140ms ease',
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.transform = 'translateY(-1px)';
        e.currentTarget.style.boxShadow = '0 3px 8px rgba(0, 0, 0, 0.12)';
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.transform = '';
        e.currentTarget.style.boxShadow = '0 1px 3px rgba(0, 0, 0, 0.08)';
      }}
    >
      <img
        src={utLogo}
        alt=""
        aria-hidden
        style={{ width: '14px', height: 'auto', display: 'block' }}
      />
      <span>Built with Understand Tech</span>
      <button
        type="button"
        onClick={dismiss}
        aria-label="Dismiss"
        title="Dismiss"
        style={{
          marginLeft: '2px',
          width: '18px',
          height: '18px',
          padding: 0,
          display: 'inline-flex',
          alignItems: 'center',
          justifyContent: 'center',
          background: 'transparent',
          border: 'none',
          color: '#6b7178',
          cursor: 'pointer',
          borderRadius: '50%',
          lineHeight: 1,
        }}
        onMouseEnter={(e) => {
          e.currentTarget.style.background = 'rgba(0, 0, 0, 0.06)';
          e.currentTarget.style.color = '#1f2328';
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.background = 'transparent';
          e.currentTarget.style.color = '#6b7178';
        }}
      >
        <svg
          width="10"
          height="10"
          viewBox="0 0 12 12"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinecap="round"
          aria-hidden
        >
          <path d="M3 3l6 6M9 3l-6 6" />
        </svg>
      </button>
    </a>
  );
}
