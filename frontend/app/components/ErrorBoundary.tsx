"use client";

import React from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";

interface Props {
  children: React.ReactNode;
}

interface State {
  hasError: boolean;
  message: string;
}

/**
 * Catches uncaught render errors anywhere in the subtree and shows a
 * recoverable error screen instead of a blank white page.
 *
 * Usage: wrap any subtree in <ErrorBoundary>...</ErrorBoundary>.
 * The root layout wraps the entire app so all pages are covered.
 */
export class ErrorBoundary extends React.Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, message: "" };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, message: error.message || "An unexpected error occurred." };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    // In production this would forward to Sentry / the backend error log.
    console.error("[ErrorBoundary]", error, info.componentStack);
  }

  handleReset = () => {
    this.setState({ hasError: false, message: "" });
  };

  render() {
    if (this.state.hasError) {
      return (
        <div
          role="alert"
          className="min-h-[60vh] flex flex-col items-center justify-center px-4 text-center"
        >
          <div className="w-16 h-16 bg-red-50 rounded-full flex items-center justify-center mx-auto mb-6">
            <AlertTriangle className="w-8 h-8 text-red-500" />
          </div>
          <h2 className="text-2xl font-bold text-slate-900 mb-2">Something went wrong</h2>
          <p className="text-slate-500 max-w-md mb-8 text-sm">{this.state.message}</p>
          <div className="flex gap-3">
            <button
              onClick={this.handleReset}
              className="inline-flex items-center gap-2 px-5 py-2.5 bg-[#1f4e78] text-white rounded-lg font-semibold text-sm hover:bg-[#2c6ea1] transition-colors"
            >
              <RefreshCw className="w-4 h-4" />
              Try again
            </button>
            <a
              href="/"
              className="inline-flex items-center gap-2 px-5 py-2.5 bg-slate-100 text-slate-700 rounded-lg font-semibold text-sm hover:bg-slate-200 transition-colors"
            >
              Go home
            </a>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
