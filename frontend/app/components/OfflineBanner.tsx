"use client";

import { useEffect, useState } from "react";
import { WifiOff, Wifi } from "lucide-react";

/**
 * Listens to the browser's online/offline events and shows a non-intrusive
 * banner when the network is unavailable.
 *
 * The PWA service worker caches the public portal pages so citizens can
 * use cached informational pages offline. Financial APIs remain NetworkOnly;
 * a cached page must not be presented as an authoritative current balance.
 */
export function OfflineBanner() {
  const [isOnline, setIsOnline] = useState(true);
  const [showReconnected, setShowReconnected] = useState(false);

  useEffect(() => {
    // Initialise from the browser's current state
    setIsOnline(navigator.onLine);

    const handleOffline = () => {
      setIsOnline(false);
      setShowReconnected(false);
    };

    const handleOnline = () => {
      setIsOnline(true);
      // Show a brief "back online" confirmation then hide
      setShowReconnected(true);
      setTimeout(() => setShowReconnected(false), 3000);
    };

    window.addEventListener("offline", handleOffline);
    window.addEventListener("online", handleOnline);
    return () => {
      window.removeEventListener("offline", handleOffline);
      window.removeEventListener("online", handleOnline);
    };
  }, []);

  if (isOnline && !showReconnected) return null;

  if (showReconnected) {
    return (
      <div
        role="status"
        aria-live="polite"
        className="fixed top-0 inset-x-0 z-50 flex items-center justify-center gap-2 bg-green-600 text-white text-sm font-semibold py-2 px-4 shadow-md"
      >
        <Wifi className="w-4 h-4" />
        You are back online.
      </div>
    );
  }

  return (
    <div
      role="alert"
      aria-live="assertive"
      className="fixed top-0 inset-x-0 z-50 flex items-center justify-center gap-2 bg-amber-500 text-white text-sm font-semibold py-2 px-4 shadow-md"
    >
      <WifiOff className="w-4 h-4" />
      You are offline. Informational pages may be available; financial records require a connection.
    </div>
  );
}
