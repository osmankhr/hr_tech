import { Button } from "./Button";

export function Modal({ title, children, onClose, size = "max-w-3xl" }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4">
      <div className={`w-full ${size} rounded-3xl bg-white p-5 shadow-xl`}>
        <div className="mb-4 flex items-start justify-between gap-4">
          <h3 className="text-lg font-semibold">{title}</h3>
          <Button variant="outline" onClick={onClose}>
            Close
          </Button>
        </div>

        {children}
      </div>
    </div>
  );
}