import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

export default function DataContextModal({ onClose }) {
  const { t } = useTranslation();
  const panelRef = useRef(null);

  const [loading, setLoading] = useState(true);
  const [content, setContent] = useState("");
  const [error, setError] = useState(null);
  const [copyFlash, setCopyFlash] = useState(false);

  const fetchContext = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/eda/context");
      if (!res.ok) {
        const text = await res.text().catch(() => "");
        throw new Error(text || t("dataContext.errorLoad"));
      }
      const text = await res.text();
      setContent(text);
    } catch (e) {
      setError(e.message || t("dataContext.errorLoad"));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchContext();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const handler = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(content);
      setCopyFlash(true);
      setTimeout(() => setCopyFlash(false), 1500);
    } catch (e) {
      setError(e.message || t("dataContext.errorCopy"));
    }
  };

  return (
    <>
      <div
        className="fixed inset-0 bg-black/40 z-40"
        onClick={onClose}
        aria-hidden="true"
      />

      <div
        ref={panelRef}
        className="fixed inset-0 z-50 flex items-center justify-center px-4"
        role="dialog"
        aria-label={t("dataContext.title")}
      >
        <div className="w-full max-w-3xl bg-gray-900 border border-gray-800 rounded-2xl shadow-2xl">
          <div className="flex items-start justify-between px-5 py-4 border-b border-gray-800">
            <div>
              <h2 className="text-base font-semibold text-gray-100 flex items-center gap-2">
                <span>📘</span>
                {t("dataContext.title")}
              </h2>
              <p className="text-xs text-gray-500 mt-0.5">{t("dataContext.subtitle")}</p>
            </div>
            <div className="flex items-center gap-2 ml-4 mt-0.5">
              <button
                onClick={handleCopy}
                disabled={!content || loading || !!error}
                className={`text-xs px-2 py-1 rounded-md border transition-colors
                            ${copyFlash
                              ? "border-emerald-500/50 text-emerald-400"
                              : "border-gray-700 text-gray-400 hover:text-gray-200 hover:border-gray-500"}
                            disabled:opacity-40 disabled:cursor-not-allowed`}
              >
                {copyFlash ? t("dataContext.copied") : t("dataContext.copy")}
              </button>
              <button
                onClick={onClose}
                className="text-gray-500 hover:text-gray-300 transition-colors text-lg leading-none"
                aria-label={t("dataContext.close")}
              >
                ✕
              </button>
            </div>
          </div>

          <div className="max-h-[75vh] overflow-y-auto px-5 py-4">
            {loading && (
              <div className="text-gray-500 text-sm animate-pulse py-8 text-center">
                {t("dataContext.loading")}
              </div>
            )}
            {!loading && error && (
              <div className="text-red-400 text-sm py-6 text-center">
                {error}
              </div>
            )}
            {!loading && !error && (
              <pre className="whitespace-pre-wrap text-xs text-gray-200 font-mono leading-relaxed">
                {content}
              </pre>
            )}
          </div>
        </div>
      </div>
    </>
  );
}
