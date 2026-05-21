"use client";

import { WifiOff, RefreshCw } from "lucide-react";

export default function OfflinePage() {
  return (
    <div className="min-h-screen bg-slate-50 flex items-center justify-center p-4">
      <div className="max-w-md w-full text-center">

        {/* Icon */}
        <div className="w-20 h-20 bg-slate-200 rounded-full flex items-center justify-center mx-auto mb-6">
          <WifiOff className="w-10 h-10 text-slate-500" />
        </div>

        {/* Heading */}
        <h1 className="text-2xl font-extrabold text-slate-900 mb-3">
          You&apos;re Offline
        </h1>

        {/* Message */}
        <p className="text-slate-500 mb-2">
          The Municipal Treasury Portal requires an internet connection to
          display up-to-date property and payment information.
        </p>
        <p className="text-slate-400 text-sm mb-8">
          Tax records are not cached offline to ensure you always see accurate,
          current data.
        </p>

        {/* Retry button */}
        <button
          onClick={() => window.location.reload()}
          className="inline-flex items-center gap-2 bg-[#1f4e78] hover:bg-[#2c6ea1] text-white font-bold px-6 py-3 rounded-xl transition-colors"
        >
          <RefreshCw className="w-4 h-4" />
          Try Again
        </button>

        {/* Footer note */}
        <p className="text-xs text-slate-400 mt-8">
          If you need to check your property status, please visit the Municipal
          Treasury Office directly or try again when your connection is restored.
        </p>
      </div>
    </div>
  );
}
