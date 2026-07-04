export function Card({ children, className = "" }) {
  return (
    <div
      className={`rounded-3xl bg-white shadow-sm ring-1 ring-slate-200 ${className}`}
    >
      {children}
    </div>
  );
}