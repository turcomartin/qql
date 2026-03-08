import { useCallback, useRef, useState } from "react";

/**
 * useChat — manages chat state and SSE streaming.
 *
 * Messages have the shape:
 *   { id, role: "user"|"assistant", text, sqlBlock, tableData, error,
 *     consultingStatus, consultingResult, questionData,
 *     thinkingText, thinkingDone, sqlThinkingText, sqlThinkingDone,
 *     triggeredBy,   // the user text that produced this assistant message (for retry)
 *     isStreaming }
 *
 * History (sent to backend) has the shape:
 *   [{ role: "user"|"assistant", content: string }]
 *
 * In one-shot mode, history sent to backend is always [].
 * Message display still shows the full conversation locally.
 */
export function useChat({ selectedTables = ["sales"] } = {}) {
  const [messages, setMessages] = useState([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [mode, setMode] = useState("conversational");
  const historyRef = useRef([]);
  const abortRef = useRef(null);

  const sendMessage = useCallback(
    async (userText) => {
      if (!userText.trim() || isStreaming) return;

      const userMsgId = Date.now();
      const asstMsgId = userMsgId + 1;

      setMessages((prev) => [
        ...prev,
        { id: userMsgId, role: "user", text: userText },
        {
          id: asstMsgId,
          role: "assistant",
          text: "",
          isStreaming: true,
          consultingStatus: null,
          consultingResult: null,
          thinkingText: "",
          thinkingDone: false,
          sqlThinkingText: "",
          sqlThinkingDone: false,
          triggeredBy: userText,
        },
      ]);
      setIsStreaming(true);

      const controller = new AbortController();
      abortRef.current = controller;

      const sentHistory = mode === "oneshot" ? [] : [...historyRef.current];

      let fullAssistantText = "";

      try {
        const response = await fetch("/chat/stream", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            message: userText,
            history: sentHistory,
            mode,
            selected_tables: selectedTables,
          }),
          signal: controller.signal,
        });

        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n\n");
          buffer = lines.pop() ?? "";

          for (const line of lines) {
            if (!line.startsWith("data: ")) continue;
            let payload;
            try {
              payload = JSON.parse(line.slice(6));
            } catch {
              continue;
            }

            if (payload.type === "consulting") {
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === asstMsgId
                    ? { ...m, consultingStatus: payload.content }
                    : m
                )
              );
            } else if (payload.type === "thinking") {
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === asstMsgId
                    ? {
                        ...m,
                        thinkingText: (m.thinkingText || "") + payload.content,
                        // Reset thinkingDone so bouncing dots reappear when new
                        // thinking arrives (e.g. native model thinking after analyst)
                        thinkingDone: false,
                      }
                    : m
                )
              );
            } else if (payload.type === "thinking_done") {
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === asstMsgId ? { ...m, thinkingDone: true } : m
                )
              );
            } else if (payload.type === "sql_thinking") {
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === asstMsgId
                    ? {
                        ...m,
                        sqlThinkingText: (m.sqlThinkingText || "") + payload.content,
                        sqlThinkingDone: false,
                      }
                    : m
                )
              );
            } else if (payload.type === "sql_thinking_done") {
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === asstMsgId ? { ...m, sqlThinkingDone: true } : m
                )
              );
            } else if (payload.type === "text") {
              fullAssistantText += payload.content;
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === asstMsgId
                    ? {
                        ...m,
                        text: fullAssistantText,
                        // Freeze the last consulting message as a persistent result badge
                        consultingResult: m.consultingResult ?? m.consultingStatus,
                        consultingStatus: null,
                      }
                    : m
                )
              );
            } else if (payload.type === "sql") {
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === asstMsgId ? { ...m, sqlBlock: payload.content } : m
                )
              );
            } else if (payload.type === "table") {
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === asstMsgId ? { ...m, tableData: payload } : m
                )
              );
            } else if (payload.type === "question") {
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === asstMsgId
                    ? { ...m, questionData: payload, consultingStatus: null }
                    : m
                )
              );
            } else if (payload.type === "error") {
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === asstMsgId ? { ...m, error: payload.content } : m
                )
              );
            } else if (payload.type === "done") {
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === asstMsgId
                    ? { ...m, isStreaming: false, consultingStatus: null, thinkingDone: true, sqlThinkingDone: true }
                    : m
                )
              );
              if (mode === "conversational") {
                historyRef.current = [
                  ...historyRef.current,
                  { role: "user", content: userText },
                  { role: "assistant", content: fullAssistantText },
                ];
              }
              setIsStreaming(false);
            }
          }
        }
      } catch (err) {
        if (err.name !== "AbortError") {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === asstMsgId
                ? {
                    ...m,
                    error: "Connection error. Is the backend running?",
                    isStreaming: false,
                    consultingStatus: null,
                    thinkingDone: true,
                    sqlThinkingDone: true,
                  }
                : m
            )
          );
        }
        setIsStreaming(false);
      }
    },
    [isStreaming, mode, selectedTables]
  );

  const stopStreaming = useCallback(() => {
    abortRef.current?.abort();
    setIsStreaming(false);
    setMessages((prev) =>
      prev.map((m) =>
        m.isStreaming
          ? { ...m, isStreaming: false, consultingStatus: null, thinkingDone: true, sqlThinkingDone: true }
          : m
      )
    );
  }, []);

  const clearChat = useCallback(() => {
    historyRef.current = [];
    setMessages([]);
  }, []);

  return { messages, isStreaming, mode, setMode, sendMessage, stopStreaming, clearChat };
}
