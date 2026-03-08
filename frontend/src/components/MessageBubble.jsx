import AnalystBlock from "./AnalystBlock";
import ErrorCard from "./ErrorCard";
import ResultTable from "./ResultTable";
import SqlBlock from "./SqlBlock";
import SqlThoughtBlock from "./SqlThoughtBlock";

/**
 * Renders a single chat message bubble.
 *
 * Assistant messages may contain:
 *   - consultingStatus: muted pulsing indicator while consultant runs
 *   - thinkingText / thinkingDone: streaming analyst reasoning block
 *   - sqlThinkingText / sqlThinkingDone: streaming SQL reasoning block
 *   - Streaming plain text (with blinking cursor while isStreaming)
 *   - A SQL code block (rendered with Prism + copy button)
 *   - A query results table
 *   - questionData: clarifying question with clickable option chips
 *   - An error card
 */
function renderTextLite(text) {
  if (!text) return null;

  const parts = text.split(/(```sql[\s\S]*?```)/gi);

  return parts.map((part, i) => {
    if (/^```sql/i.test(part)) return null;

    const html = part
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
      .replace(/`([^`]+)`/g, '<code class="bg-gray-700 px-1 rounded text-sm font-mono">$1</code>')
      .replace(/\n/g, "<br />");

    return <span key={i} dangerouslySetInnerHTML={{ __html: html }} />;
  });
}

function ConsultingIndicator({ status }) {
  return (
    <div className="flex items-center gap-2 text-gray-500 text-sm italic">
      <span className="inline-flex gap-0.5">
        <span className="w-1.5 h-1.5 rounded-full bg-indigo-500 animate-bounce" style={{ animationDelay: "0ms" }} />
        <span className="w-1.5 h-1.5 rounded-full bg-indigo-500 animate-bounce" style={{ animationDelay: "150ms" }} />
        <span className="w-1.5 h-1.5 rounded-full bg-indigo-500 animate-bounce" style={{ animationDelay: "300ms" }} />
      </span>
      {status}
    </div>
  );
}

function QuestionCard({ questionData, onOption }) {
  const { content, options = [] } = questionData;
  return (
    <div className="mt-2 space-y-2">
      <p className="text-gray-200">{content}</p>
      <div className="flex flex-wrap gap-2">
        {options.map((opt, i) => (
          <button
            key={i}
            onClick={() => onOption(opt)}
            className="px-3 py-1.5 rounded-xl border border-indigo-700 bg-indigo-950/40
                       text-indigo-300 text-sm hover:bg-indigo-900/40 hover:border-indigo-500
                       transition-all"
          >
            {opt}
          </button>
        ))}
      </div>
    </div>
  );
}

export default function MessageBubble({ message, onSend, onClear }) {
  const {
    role, text, sqlBlock, tableData, error,
    consultingStatus, consultingResult, questionData,
    thinkingText, thinkingDone,
    sqlThinkingText, sqlThinkingDone,
    triggeredBy,
    isStreaming,
  } = message;

  const isUser = role === "user";

  // Show analyst block if there's thinking content OR if streaming hasn't produced
  // any consulting/text yet (means analyst is still waiting for its first chunk)
  const showAnalystBlock = !isUser && (
    thinkingText ||
    (!thinkingDone && isStreaming && !consultingStatus && !text)
  );

  const showSqlThoughtBlock = !isUser && Boolean(sqlThinkingText);

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"} mb-4`}>
      {!isUser && (
        <div className="w-8 h-8 rounded-full bg-indigo-600 flex items-center justify-center text-white text-xs font-bold mr-3 mt-1 flex-shrink-0">
          Q
        </div>
      )}

      <div
        className={`max-w-3xl rounded-2xl px-4 py-3 ${
          isUser
            ? "bg-indigo-600 text-white rounded-tr-sm"
            : "bg-gray-800 text-gray-100 rounded-tl-sm"
        }`}
      >
        {/* Consulting in-progress indicator (disappears once text arrives) */}
        {consultingStatus && !isUser && (
          <ConsultingIndicator status={consultingStatus} />
        )}

        {/* Analyst reasoning block — streams before SQL generation */}
        {showAnalystBlock && (
          <AnalystBlock
            text={thinkingText}
            done={thinkingDone}
          />
        )}

        {showSqlThoughtBlock && (
          <SqlThoughtBlock
            text={sqlThinkingText}
            done={sqlThinkingDone}
          />
        )}

        {/* Consulting result badge — persists after text/SQL/table arrive */}
        {consultingResult && !consultingStatus && !isUser && (
          <div className="flex items-center gap-1.5 text-xs text-gray-500 mb-2">
            <span className="text-emerald-500">✓</span>
            <span>{consultingResult}</span>
          </div>
        )}

        {/* Text content */}
        <div className={`leading-relaxed ${isStreaming && !text && !consultingStatus && !showAnalystBlock ? "cursor-blink" : ""}`}>
          {text ? (
            <span className={isStreaming ? "cursor-blink" : ""}>
              {renderTextLite(text)}
            </span>
          ) : isStreaming && !consultingStatus && !showAnalystBlock ? (
            <span className="cursor-blink" />
          ) : null}
        </div>

        {/* SQL block */}
        {sqlBlock && !isUser && <SqlBlock sql={sqlBlock} />}

        {/* Query results table */}
        {tableData && !isUser && <ResultTable {...tableData} />}

        {/* Clarifying question */}
        {questionData && !isUser && (
          <QuestionCard
            questionData={questionData}
            onOption={(opt) => onSend && onSend(opt)}
          />
        )}

        {/* Error card */}
        {error && !isUser && (
          <ErrorCard
            message={error}
            onRetry={triggeredBy && onSend ? () => onSend(triggeredBy) : undefined}
            onClear={onClear}
          />
        )}
      </div>

      {isUser && (
        <div className="w-8 h-8 rounded-full bg-gray-600 flex items-center justify-center text-white text-xs font-bold ml-3 mt-1 flex-shrink-0">
          U
        </div>
      )}
    </div>
  );
}
