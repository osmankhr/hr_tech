import { useEffect } from "react";
import { Button } from "./Button";

export function Modal({
  title,
  children,
  onClose,
  size = "max-w-3xl",
  footer = null,
}) {
  // Close on Escape key press
  useEffect(() => {
    function handleKeyDown(e) {
      if (e.key === "Escape" && onClose) {
        onClose();
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  // Lock background body scroll while modal is mounted
  useEffect(() => {
    const originalOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = originalOverflow;
    };
  }, []);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 p-3 sm:p-5 backdrop-blur-xs overflow-y-auto"
      onClick={(e) => {
        if (e.target === e.currentTarget && onClose) {
          onClose();
        }
      }}
      role="dialog"
      aria-modal="true"
    >
      <div
        className={`relative flex flex-col max-h-[92vh] w-full ${size} rounded-2xl bg-white shadow-2xl border border-slate-200 overflow-hidden my-auto`}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Fixed / Sticky Header */}
        <div className="flex shrink-0 items-center justify-between border-b border-slate-200 bg-slate-50/90 px-6 py-4">
          <h3 className="text-lg font-semibold text-slate-900 truncate pr-4">
            {title}
          </h3>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={onClose}
              className="text-xs font-medium text-slate-600 hover:text-slate-900"
            >
              Close
            </Button>
            <button
              type="button"
              onClick={onClose}
              className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-slate-400 hover:bg-slate-200/70 hover:text-slate-700 transition-colors focus:outline-none focus:ring-2 focus:ring-indigo-500"
              aria-label="Close modal"
            >
              <svg
                className="h-5 w-5"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                strokeWidth={2}
              >
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        </div>

        {/* Scrollable Content Body */}
        <div className="flex-1 overflow-y-auto px-6 py-5 overscroll-contain">
          {children}
        </div>

        {/* Optional Sticky Footer */}
        {footer && (
          <div className="flex shrink-0 items-center justify-end gap-3 border-t border-slate-200 bg-slate-50/90 px-6 py-3.5">
            {footer}
          </div>
        )}
      </div>
    </div>
  );
}
