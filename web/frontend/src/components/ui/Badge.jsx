export function Badge({ children, tone = "gray" }) {
  const tones = {
    green: "border-emerald-200 bg-emerald-50 text-emerald-700",
    brand: "border-indigo-200 bg-indigo-50 text-indigo-700",
    amber: "border-amber-200 bg-amber-50 text-amber-700",
    gray: "border-slate-200 bg-slate-50 text-slate-700",
    red: "border-red-200 bg-red-50 text-red-700",
  };

  return (
    <span
      className={`inline-flex items-center rounded-full border px-2.5 py-1 text-xs font-medium ${
        tones[tone] || tones.gray
      }`}
    >
      {children}
    </span>
  );
}
``