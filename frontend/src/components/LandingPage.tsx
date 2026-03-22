import { useState } from 'react';

interface Props {
  onSignIn: () => void;
  onEmailSignIn: (email: string, password: string) => Promise<string | null>;
  onEmailSignUp: (email: string, password: string) => Promise<string | null>;
}

export function LandingPage({ onSignIn, onEmailSignIn, onEmailSignUp }: Props) {
  const [tab, setTab] = useState<'signin' | 'signup'>('signin');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [name, setName] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [googleLoading, setGoogleLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setInfo(null);
    setLoading(true);
    const fn = tab === 'signin' ? onEmailSignIn : onEmailSignUp;
    const err = await fn(email, password);
    setLoading(false);
    if (err) {
      setError(err);
    } else if (tab === 'signup') {
      setInfo('Account created! Check your email to confirm, then sign in.');
    }
  }

  function handleGoogleClick() {
    setGoogleLoading(true);
    onSignIn();
  }

  return (
    <div className="lp-root">
      <div className="lp-card">
        {/* Logo */}
        <div className="lp-logo">
          CEO<span>Claw</span>
        </div>
        <h2 className="lp-heading">
          {tab === 'signin' ? 'Welcome back' : 'Create your account'}
        </h2>
        <p className="lp-sub">
          {tab === 'signin'
            ? 'Sign in to continue building'
            : 'Start building for free — no credit card needed'}
        </p>

        {/* Google button */}
        <button
          className="lp-google-btn"
          onClick={handleGoogleClick}
          disabled={googleLoading}
        >
          {googleLoading ? (
            <span className="lp-spinner" />
          ) : (
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
              <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4"/>
              <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/>
              <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" fill="#FBBC05"/>
              <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335"/>
            </svg>
          )}
          Continue with Google
        </button>

        {/* Divider */}
        <div className="lp-divider"><span>or</span></div>

        {/* Tabs */}
        <div className="lp-tabs">
          <button
            className={`lp-tab${tab === 'signin' ? ' lp-tab--active' : ''}`}
            onClick={() => { setTab('signin'); setError(null); setInfo(null); }}
          >Sign in</button>
          <button
            className={`lp-tab${tab === 'signup' ? ' lp-tab--active' : ''}`}
            onClick={() => { setTab('signup'); setError(null); setInfo(null); }}
          >Sign up</button>
        </div>

        {/* Form */}
        <form className="lp-form" onSubmit={handleSubmit}>
          {tab === 'signup' && (
            <div className="lp-field">
              <label className="lp-label">Full name</label>
              <input
                className="lp-input"
                type="text"
                placeholder="Alex Johnson"
                value={name}
                onChange={e => setName(e.target.value)}
                autoComplete="name"
              />
            </div>
          )}
          <div className="lp-field">
            <label className="lp-label">Email</label>
            <input
              className="lp-input"
              type="email"
              placeholder="you@example.com"
              value={email}
              onChange={e => setEmail(e.target.value)}
              required
              autoComplete="email"
            />
          </div>
          <div className="lp-field">
            <div className="lp-label-row">
              <label className="lp-label">Password</label>
              {tab === 'signin' && (
                <button type="button" className="lp-forgot">Forgot password?</button>
              )}
            </div>
            <input
              className="lp-input"
              type="password"
              placeholder={tab === 'signup' ? 'At least 8 characters' : '••••••••'}
              value={password}
              onChange={e => setPassword(e.target.value)}
              required
              autoComplete={tab === 'signin' ? 'current-password' : 'new-password'}
            />
          </div>

          {error && (
            <div className="lp-error">
              <svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor">
                <path d="M8 1a7 7 0 100 14A7 7 0 008 1zm0 3.5a.75.75 0 01.75.75v3a.75.75 0 01-1.5 0v-3A.75.75 0 018 4.5zm0 7a1 1 0 110-2 1 1 0 010 2z"/>
              </svg>
              {error}
            </div>
          )}
          {info && (
            <div className="lp-info">
              <svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor">
                <path d="M8 1a7 7 0 100 14A7 7 0 008 1zm-.75 3.75a.75.75 0 011.5 0v4.5a.75.75 0 01-1.5 0v-4.5zm.75 7.25a1 1 0 110-2 1 1 0 010 2z"/>
              </svg>
              {info}
            </div>
          )}

          <button className="lp-submit" type="submit" disabled={loading}>
            {loading
              ? <><span className="lp-spinner lp-spinner--light" /> Please wait…</>
              : tab === 'signin' ? 'Sign in' : 'Create account'}
          </button>
        </form>

        <p className="lp-footer">
          By continuing, you agree to our{' '}
          <a href="#" className="lp-link">Terms</a> and{' '}
          <a href="#" className="lp-link">Privacy Policy</a>.
        </p>
      </div>
    </div>
  );
}
