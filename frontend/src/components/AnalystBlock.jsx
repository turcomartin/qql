/**
 * AnalystBlock — streaming amber collapsible block for business analyst reasoning.
 *
 * Shows the analyst's 3-section reasoning (Business Angle, SQL Challenge, Approach)
 * as it streams in real-time. After streaming completes (done=true), the block
 * becomes collapsible.
 *
 * Props:
 *   text     — accumulated streaming text (grows as chunks arrive)
 *   done     — true once thinking_done event received
 */

import { useState } from "react";
import { useTranslation } from "react-i18next";

/**
 * Render the analyst text, converting ## Section headers to styled amber headings
 * and leaving regular text as inline spans.
 */
function renderAnalystText(text) {
  if (!text) return null;

  return text.split("\n").map((line, i) => {
    const headerMatch = line.match(/^##\s+(.+)$/);
    if (headerMatch) {
      return (
        <div key={i} className="text-amber-400 font-semibold text-xs uppercase tracking-wide mt-3 mb-0.5 first:mt-0">
          {headerMatch[1]}
        </div>
      );
    }

    if (!line.trim()) return <div key={i} className="h-1" />;

    // Render inline: bold + code
    const html = line
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
      .replace(/`([^`]+)`/g, '<code class="bg-amber-950/60 px-1 rounded text-xs font-mono text-amber-300">$1</code>');

    return (
      <span
        key={i}
        className="block text-amber-100/80 text-sm leading-relaxed"
        dangerouslySetInnerHTML={{ __html: html }}
      />
    );
  });
}

export default function AnalystBlock({ text, done }) {
  const { t } = useTranslation();
  const [collapsed, setCollapsed] = useState(false);

  const hasContent = Boolean(text && text.trim());

  // Don't render anything if streaming hasn't started yet and block is done
  if (done && !hasContent) return null;

  return (
    <div className="mb-3 rounded-lg border border-amber-900/40 bg-amber-950/30 overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-amber-900/30">
        <div className="flex items-center gap-2">
          <span className="text-amber-400 text-sm">🔍</span>
          <span className="text-amber-400 text-xs font-semibold uppercase tracking-wide">
            {done ? t("analyst.title") : t("analyst.analyzing")}
          </span>
          {/* Bouncing dots while streaming */}
          {!done && (
            <span className="inline-flex gap-0.5 ml-1">
              <span className="w-1 h-1 rounded-full bg-amber-500 animate-bounce" style={{ animationDelay: "0ms" }} />
              <span className="w-1 h-1 rounded-full bg-amber-500 animate-bounce" style={{ animationDelay: "150ms" }} />
              <span className="w-1 h-1 rounded-full bg-amber-500 animate-bounce" style={{ animationDelay: "300ms" }} />
            </span>
          )}
        </div>

        {/* Collapse toggle — only shown after streaming completes */}
        {done && hasContent && (
          <button
            onClick={() => setCollapsed((c) => !c)}
            className="text-xs text-amber-600 hover:text-amber-400 transition-colors"
          >
            {collapsed ? t("analyst.show") : t("analyst.hide")}
          </button>
        )}
      </div>

      {/* Body — hidden when collapsed */}
      {!collapsed && (
        <div className="px-3 py-2.5">
          {hasContent ? (
            renderAnalystText(text)
          ) : (
            // Blinking cursor while waiting for first chunk
            <span className="cursor-blink text-amber-600/50 text-sm">▌</span>
          )}
        </div>
      )}
    </div>
  );
}
