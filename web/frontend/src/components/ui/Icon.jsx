function SimpleIcon({ symbol, className = "" }) {
  return (
    <span
      className={`inline-flex items-center justify-center leading-none ${className}`}
      aria-hidden="true"
    >
      {symbol}
    </span>
  );
}

export const Icons = {
  Briefcase: (props) => <SimpleIcon symbol="💼" {...props} />,
  Users: (props) => <SimpleIcon symbol="👥" {...props} />,
  Refresh: (props) => <SimpleIcon symbol="🔄" {...props} />,
  Plus: (props) => <SimpleIcon symbol="➕" {...props} />,
  Search: (props) => <SimpleIcon symbol="🔎" {...props} />,
  Check: (props) => <SimpleIcon symbol="✅" {...props} />,
  Clock: (props) => <SimpleIcon symbol="⏱️" {...props} />,
  Archive: (props) => <SimpleIcon symbol="📦" {...props} />,
  Database: (props) => <SimpleIcon symbol="🗄️" {...props} />,
  Chart: (props) => <SimpleIcon symbol="📊" {...props} />,
  Filter: (props) => <SimpleIcon symbol="🔽" {...props} />,
};