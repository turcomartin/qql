import { useState } from "react";
import { useTranslation } from "react-i18next";

import EDAProgress from "./EDAProgress";

/**
 * EDARefreshModal — shown automatically after table selection and accessible
 * via the 📖 book icon in the header.
 *
 * Two views:
 *   "prompt"  — asks the user whether to regenerate insights or use existing ones
 *   "running" — shows the live EDAProgress checklist while the EDA agent runs
 *
 * Props:
 *   onClose      — called when the modal should be dismissed
 *   onRefreshed  — optional callback fired after a successful regeneration
 *                  (used to refresh the 🧠 skill badge count in the header)
 */
export default function EDARefreshModal({ onClose, onRefreshed }) {
  const { t } = useTranslation();
  const [running, setRunning] = useState(false);

  const handleRegenerate = () => {
    setRunning(true);
    // Fire-and-forget — EDAProgress subscribes to GET /eda/events via SSE
    // and is the authoritative source for when the run completes.
    fetch("/eda/refresh", { method: "POST" }).catch(() => {});
  };

  const handleDone = () => {
    onRefreshed?.();
    onClose();
  };

  return (
    <>
      {/* Backdrop — only dismisses when not running */}
      <div
        className="fixed inset-0 bg-black/40 z-40"
        onClick={!running ? onClose : undefined}
      />

      {/* Modal */}
      <div className="fixed inset-0 z-50 flex items-center justify-center px-4">
        <div className="w-full max-w-sm bg-gray-900 border border-gray-800 rounded-2xl shadow-xl">

          {/* Header */}
          <div className="px-6 pt-6 pb-4 border-b border-gray-800">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h2 className="text-base font-semibold text-gray-100 flex items-center gap-2">
                  <span className="text-base leading-none">📖</span>
                  {t("edaRefresh.title")}
                </h2>
                <p className="text-xs text-gray-500 mt-0.5">{t("edaRefresh.subtitle")}</p>
              </div>
              {!running && (
                <button
                  onClick={onClose}
                  className="text-gray-600 hover:text-gray-400 transition-colors p-0.5 flex-shrink-0 mt-0.5"
                  aria-label="Close"
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              )}
            </div>
          </div>

          {/* Body */}
          <div className="px-6 py-5">
            {running ? (
              <EDAProgress onDone={handleDone} />
            ) : (
              <>
                <p className="text-sm text-gray-400 leading-relaxed">
                  {t("edaRefresh.prompt")}
                </p>
                <div className="flex flex-col gap-2 mt-5">
                  <button
                    onClick={handleRegenerate}
                    className="w-full py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-500
                               text-white text-sm font-medium transition-colors"
                  >
                    {t("edaRefresh.regenerate")}
                  </button>
                  <button
                    onClick={onClose}
                    className="w-full py-2.5 rounded-xl border border-gray-700
                               text-gray-400 hover:text-gray-200 hover:border-gray-500
                               text-sm transition-colors"
                  >
                    {t("edaRefresh.useExisting")}
                  </button>
                </div>
              </>
            )}
          </div>

        </div>
      </div>
    </>
  );
}
