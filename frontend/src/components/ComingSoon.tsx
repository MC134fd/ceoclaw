interface Props {
  title: string;
}

export function ComingSoon({ title }: Props) {
  return (
    <div className="dashboard-main">
      <div className="coming-soon">
        <div className="coming-soon-icon">
          <svg width="48" height="48" viewBox="0 0 48 48" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="24" cy="24" r="20" />
            <path d="M24 14v10l7 7" />
          </svg>
        </div>
        <h2>{title}</h2>
        <p>This feature is coming soon. Stay tuned!</p>
      </div>
    </div>
  );
}
