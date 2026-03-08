import { useTranslation } from "react-i18next";

export default function ErrorCard({ message, onRetry, onClear }) {
  const { t } = useTranslation();
  return (
    <div className="mt-2 rounded-lg bg-red-950/60 border border-red-800 text-red-300 text-sm overflow-hidden">
      <div className="px-3 py-2">
        <span className="font-medium mr-1">Error:</span>
        {message}
      </div>
      {(onRetry || onClear) && (
        <div className="flex gap-2 px-3 py-2 border-t border-red-900/60 bg-red-950/30">
          {onRetry && (
            <button
              onClick={onRetry}
              className="flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-md
                         bg-red-900/40 text-red-300 border border-red-800
                         hover:bg-red-800/40 hover:text-red-200 hover:border-red-700
                         transition-all"
            >
              ↺ {t("error.retry")}
            </button>
          )}
          {onClear && (
            <button
              onClick={onClear}
              className="flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-md
                         bg-gray-800/60 text-gray-400 border border-gray-700
                         hover:bg-gray-700/60 hover:text-gray-200 hover:border-gray-600
                         transition-all"
            >
              + {t("error.newConversation")}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
