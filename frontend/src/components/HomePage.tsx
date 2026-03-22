import { useEffect } from 'react';

interface Props {
  onGetStarted: () => void;
}

export function HomePage({ onGetStarted }: Props) {
  useEffect(() => {
    function handleMessage(e: MessageEvent) {
      if (e.data === 'goto-signin') {
        onGetStarted();
      }
    }
    window.addEventListener('message', handleMessage);
    return () => window.removeEventListener('message', handleMessage);
  }, [onGetStarted]);

  return (
    <iframe
      src="/aurora.html"
      style={{ width: '100%', height: '100vh', border: 'none', display: 'block' }}
      title="CEOClaw"
    />
  );
}
