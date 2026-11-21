import React from "react";

export class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, errorInfo) {
    console.error("ErrorBoundary caught an unhandled error:", error, errorInfo);
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null });
    if (this.props.onReset) {
      this.props.onReset();
    }
  };

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex min-h-[300px] flex-col items-center justify-center rounded-xl border border-red-200 bg-red-50/60 p-6 text-center">
          <div className="flex h-12 w-12 items-center justify-center rounded-full bg-red-100 text-red-600">
            <svg
              className="h-6 w-6"
              fill="none"
              viewBox="0 0 24 24"
              strokeWidth="1.5"
              stroke="currentColor"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z"
              />
            </svg>
          </div>
          <h3 className="mt-3 text-base font-semibold text-red-900">
            {this.props.title || "An error occurred in this view"}
          </h3>
          <p className="mt-1 max-w-md text-sm text-red-700">
            {this.state.error?.message || "An unexpected error occurred while rendering this section."}
          </p>
          <div className="mt-4 flex items-center gap-3">
            <button
              type="button"
              onClick={this.handleReset}
              className="rounded-lg border border-red-300 bg-white px-3.5 py-1.5 text-xs font-semibold text-red-800 shadow-sm hover:bg-red-50"
            >
              Try Again
            </button>
            <button
              type="button"
              onClick={() => window.location.reload()}
              className="rounded-lg bg-red-700 px-3.5 py-1.5 text-xs font-semibold text-white shadow-sm hover:bg-red-800"
            >
              Reload Page
            </button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
