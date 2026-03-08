import { useCallback, useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";

export default function InputBar({ onSend, isStreaming, onStop }) {
  const { t } = useTranslation();
  const textareaRef = useRef(null);

  const autoResize = () => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  };

  useEffect(() => {
    autoResize();
  }, []);

  const handleKeyDown = useCallback(
    (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [isStreaming]
  );

  const handleSend = useCallback(() => {
    const el = textareaRef.current;
    if (!el) return;
    const text = el.value.trim();
    if (!text || isStreaming) return;
    onSend(text);
    el.value = "";
    el.style.height = "auto";
  }, [isStreaming, onSend]);

  return (
    <div className="border-t border-gray-800 bg-gray-950 px-4 py-3">
      <div className="max-w-4xl mx-auto flex gap-3 items-end">
        <textarea
          ref={textareaRef}
          rows={1}
          onInput={autoResize}
          onKeyDown={handleKeyDown}
          disabled={isStreaming}
          placeholder={t("inputPlaceholder")}
          className="flex-1 resize-none rounded-xl bg-gray-800 text-gray-100 placeholder-gray-500
                     px-4 py-3 focus:outline-none focus:ring-2 focus:ring-indigo-500
                     disabled:opacity-50 disabled:cursor-not-allowed transition-all"
        />
        {isStreaming ? (
          <button
            onClick={onStop}
            className="px-4 py-3 rounded-xl bg-gray-700 text-gray-200 hover:bg-gray-600
                       transition-colors text-sm font-medium flex-shrink-0"
          >
            {t("stop")}
          </button>
        ) : (
          <button
            onClick={handleSend}
            className="px-4 py-3 rounded-xl bg-indigo-600 text-white hover:bg-indigo-500
                       transition-colors text-sm font-medium flex-shrink-0"
          >
            {t("send")}
          </button>
        )}
      </div>
      <p className="text-xs text-gray-600 text-center mt-1">
        {t("disclaimer")}
      </p>
    </div>
  );
}
