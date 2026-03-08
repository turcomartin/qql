/**
 * EDAProgress — live checklist of EDA phases driven by Server-Sent Events.
 *
 * Connects to GET /eda/events which streams phase updates as the EDA agent
 * moves through:
 *   discover → profile → interpret → context → skill
 *
 * Each phase shows one of four states:
 *   pending  — grey hollow circle (not started)
 *   running  — indigo spinner (in progress)
 *   done     — green checkmark
 *   skip     — grey dash (phase was unavailable, e.g. LLM offline)
 *
 * An optional detail string (e.g. "product_name (3/7)") is shown right-
 * aligned in monospace next to each row.
 *
 * Calls onDone() with a short delay after receiving the "done" or
 * "cancelled" SSE event so the UI briefly shows the final state before
 * transitioning away.
 *
 * A "Stop" button is shown while the run is active.  Clicking it sends
 * POST /eda/cancel; the agent stops at the next checkpoint and the SSE
 * stream delivers a "cancelled" event.
 */

import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

// Ordered phase keys — must match backend/eda/progress.py PHASE_KEYS
const PHASE_KEYS = ["discover", "profile", "interpret", "context", "skill"];

function StatusIcon({ status }) {
  switch (status) {
    case "done":
      return <span className="text-emerald-500 text-xs leading-none">✓</span>;
    case "skip":
      return <span className="text-gray-600 text-xs leading-none">–</span>;
    case "start":
    case "update":
      return (
        <span className="inline-block animate-spin text-indigo-400 leading-none text-[11px]">
          ↻
        </span>
      );
    default: // pending
      return (
        <span className="w-2.5 h-2.5 rounded-full border border-gray-700 inline-block flex-shrink-0" />
      );
  }
}

export default function EDAProgress({ onDone }) {
  const { t } = useTranslation();

  const [phases, setPhases] = useState(
    PHASE_KEYS.map((key) => ({ key, status: "pending", detail: "" }))
  );
  const [stopping, setStopping] = useState(false);
  const [settled, setSettled] = useState(false); // true after done/cancelled

  const doneCalledRef = useRef(false);
  const esRef = useRef(null);

  useEffect(() => {
    const es = new EventSource("/eda/events");
    esRef.current = es;

    es.onmessage = (e) => {
      let msg;
      try {
        msg = JSON.parse(e.data);
      } catch {
        return;
      }

      if (msg.type === "snapshot") {
        // Initial state — merge server phases into our ordered list.
        setPhases(
          PHASE_KEYS.map((key) => {
            const p = (msg.phases || []).find((x) => x.phase === key);
            return { key, status: p?.status ?? "pending", detail: p?.detail ?? "" };
          })
        );
      } else if (msg.type === "phase") {
        setPhases((prev) =>
          prev.map((p) =>
            p.key === msg.phase
              ? { ...p, status: msg.status, detail: msg.detail ?? "" }
              : p
          )
        );
      } else if (msg.type === "done" || msg.type === "cancelled") {
        es.close();
        triggerDone();
      }
    };

    es.onerror = () => {
      es.close();
      // Treat a connection error as completion so the UI doesn't hang.
      triggerDone();
    };

    return () => {
      es.close();
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const triggerDone = () => {
    if (!doneCalledRef.current) {
      doneCalledRef.current = true;
      setSettled(true);
      // Small delay so the user can see all phases green before transitioning.
      setTimeout(() => onDone?.(), 700);
    }
  };

  const handleStop = async () => {
    setStopping(true);
    try {
      await fetch("/eda/cancel", { method: "POST" });
    } catch {
      // Ignore network errors — the SSE stream will signal completion
      // (or the error handler above will call triggerDone).
    }
  };

  const isActive = phases.some(
    (p) => p.status === "start" || p.status === "update"
  );

  return (
    <div className="space-y-1.5 py-0.5">
      {phases.map(({ key, status, detail }) => {
        const isRunning = status === "start" || status === "update";
        const isDone = status === "done";
        const isSkipped = status === "skip";

        return (
          <div key={key} className="flex items-center gap-2 min-w-0">
            {/* Status indicator — fixed width so labels align */}
            <span className="w-3.5 h-3.5 flex-shrink-0 flex items-center justify-center">
              <StatusIcon status={status} />
            </span>

            {/* Phase label */}
            <span
              className={`text-xs transition-colors truncate ${
                isDone
                  ? "text-gray-500"
                  : isRunning
                  ? "text-indigo-300"
                  : isSkipped
                  ? "text-gray-600 line-through"
                  : "text-gray-600"
              }`}
            >
              {t(`eda.phase.${key}`, { defaultValue: key })}
            </span>

            {/* Detail — right-aligned, truncated, only shown when non-empty */}
            {detail && (
              <span className="text-[10px] text-gray-600 font-mono ml-auto flex-shrink-0 max-w-[130px] truncate">
                {detail}
              </span>
            )}
          </div>
        );
      })}

      {/* Stop button — shown while the run is active and not yet settled */}
      {!settled && (isActive || stopping) && (
        <div className="flex justify-end pt-0.5">
          <button
            onClick={handleStop}
            disabled={stopping}
            className="text-[11px] text-gray-600 hover:text-red-400 disabled:opacity-40
                       transition-colors leading-none"
          >
            {stopping ? t("eda.stopping") : t("eda.stopButton")}
          </button>
        </div>
      )}
    </div>
  );
}
