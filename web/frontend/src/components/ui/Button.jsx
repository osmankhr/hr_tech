export function Button({
  children,
  className = "",
  variant = "primary",
  disabled = false,
  ...props
}) {
  const variants = {
    primary: "border-indigo-700 bg-indigo-700 text-white hover:bg-indigo-800",
    dark: "border-slate-900 bg-slate-900 text-white hover:bg-slate-800",
    outline: "border-slate-300 bg-white text-slate-700 hover:bg-slate-50",
    soft: "border-slate-100 bg-slate-100 text-slate-700 hover:bg-slate-200",
    danger: "border-red-600 bg-red-600 text-white hover:bg-red-700",
  };

  return (
    <button
      className={`inline-flex items-center justify-center gap-2 rounded-lg border px-4 py-2 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-50 ${variants[variant]} ${className}`}
      disabled={disabled}
      {...props}
    >
      {children}
    </button>
  );
}