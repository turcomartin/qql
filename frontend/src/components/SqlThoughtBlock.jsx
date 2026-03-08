import { useState } from "react";
import { useTranslation } from "react-i18next";

function renderSqlThoughtText(text, maxLines = null) {
  if (!text) return null;
  const lines = text.split("\n");
  const sliced = maxLines ? lines.slice(0, maxLines) : lines;

  return sliced.map((line, i) => {
    if (!line.trim()) return <div key={i} className="h-1" />;

    const html = line
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
      .replace(/`([^`]+)`/g, '<code class="bg-indigo-950/60 px-1 rounded text-xs font-mono text-indigo-300">$1</code>');

    return (
      <span
        key={i}
        className="block text-indigo-100/80 text-sm leading-relaxed"
        dangerouslySetInnerHTML={{ __html: html }}
      />
    );
  });
}

export default function SqlThoughtBlock({ text, done }) {
  const { t } = useTranslation();
  const [collapsed, setCollapsed] = useState(true);

  const hasContent = Boolean(text && text.trim());

  if (done && !hasContent) return null;

  return (
    <div className="mb-3 rounded-lg border border-indigo-900/40 bg-indigo-950/30 overflow-hidden">
      <div className="flex items-center justify-between px-3 py-2 border-b border-indigo-900/30">
        <div className="flex items-center gap-2">
          <span className="text-indigo-400 text-sm">🧩</span>
          <span className="text-indigo-400 text-xs font-semibold uppercase tracking-wide">
            {done ? t("sqlThoughts.title") : t("sqlThoughts.analyzing")}
          </span>
          {!done && (
            <span className="inline-flex gap-0.5 ml-1">
              <span className="w-1 h-1 rounded-full bg-indigo-500 animate-bounce" style={{ animationDelay: "0ms" }} />
              <span className="w-1 h-1 rounded-full bg-indigo-500 animate-bounce" style={{ animationDelay: "150ms" }} />
              <span className="w-1 h-1 rounded-full bg-indigo-500 animate-bounce" style={{ animationDelay: "300ms" }} />
            </span>
          )}
        </div>

        {hasContent && (
          <button
            onClick={() => setCollapsed((c) => !c)}
            className="text-xs text-indigo-600 hover:text-indigo-400 transition-colors"
          >
            {collapsed ? t("sqlThoughts.show") : t("sqlThoughts.hide")}
          </button>
        )}
      </div>

      <div className="px-3 py-2.5">
        {hasContent ? (
          collapsed
            ? renderSqlThoughtText(text, 2)
            : renderSqlThoughtText(text)
        ) : (
          <span className="cursor-blink text-indigo-600/50 text-sm">▌</span>
        )}
      </div>
    </div>
  );
}
