import { Card } from "./Card";

export function KPI({ icon: Icon, label, value, sub }) {
  return (
    <Card className="p-5">
      <div className="flex items-center gap-4">
        <div className="rounded-2xl bg-slate-900 p-3 text-white">
          <Icon className="h-5 w-5" />
        </div>

        <div>
          <p className="text-sm text-slate-500">{label}</p>
          <p className="text-2xl font-semibold text-slate-900">{value}</p>
          <p className="text-xs text-slate-400">{sub}</p>
        </div>
      </div>
    </Card>
  );
}