export function Badge({ children, tone = "gray" }) {
  const tones = {
    green: "border-emerald-200 bg-emerald-50 text-emerald-700",
    orange: "border-orange-200 bg-orange-50 text-orange-700",
    amber: "border-amber-200 bg-amber-50 text-amber-700",
    purple: "border-purple-200 bg-purple-50 text-purple-700",
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