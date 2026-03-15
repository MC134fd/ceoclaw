/**
 * LandingPage — shown when Supabase auth is enabled but the user is not
 * signed in. Provides a single "Continue with Google" CTA.
 */
interface Props {
  onSignIn: () => void;
  isLoading?: boolean;
}

export function LandingPage({ onSignIn, isLoading }: Props) {
  return (
    <div className="landing-root">
      <div className="landing-card">
        {/* Brand */}
        <h1 className="landing-brand">
          CEO<span style={{ color: 'var(--accent)' }}>Claw</span>
        </h1>
        <p className="landing-tagline">
          Describe your product — get a live website in seconds.
        </p>

        {/* Feature list */}
        <ul className="landing-features">
          <li>AI-generated landing pages &amp; app UIs</li>
          <li>Iterative chat-based edits</li>
          <li>Version history &amp; one-click restore</li>
          <li>10 free credits on sign-up</li>
        </ul>

        {/* CTA */}
        <button
          className="landing-signin-btn"
          onClick={onSignIn}
          disabled={isLoading}
        >
          {isLoading ? 'Redirecting…' : 'Continue with Google'}
        </button>

        <p className="landing-footnote">
          By signing in you agree to use this service responsibly.
        </p>
      </div>
    </div>
  );
}
