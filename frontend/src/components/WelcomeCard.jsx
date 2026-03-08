/**
 * WelcomeCard — shown in the empty chat state.
 *
 * Shows table stats + abbreviation skill status.
 *
 * While the EDA agent is running (or just triggered by the user), renders
 * <EDAProgress> — a live checklist fed by the GET /eda/events SSE stream.
 * Once done, the badge shows how many abbreviations were learned.
 *
 * If no abbreviations exist yet and EDA is idle, an "Analyze data" button
 * lets the user trigger it manually.
 */

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import EDAProgress from "./EDAProgress";

export default function WelcomeCard({
  selectedTables,
  onOpenSkill,
  onOpenContext,
}) {
  const { t } = useTranslation();
  const [tables, setTables] = useState([]);
  const [skillCount, setSkillCount] = useState(null); // null = loading
  const [analyzing, setAnalyzing] = useState(false);

  // ---------- helpers ----------

  const fetchSkill = async () => {
    try {
      const r = await fetch("/eda/skill");
      if (r.ok) {
        const data = await r.json();
        setSkillCount(data?.acronyms?.length ?? 0);
      } else {
        setSkillCount(0);
      }
    } catch {
      setSkillCount(0);
    }
  };

  // ---------- mount: load tables + skill + check if EDA is already running ----------

  useEffect(() => {
    Promise.all([
      fetch("/tables").then((r) => r.ok ? r.json() : []).catch(() => []),
      fetch("/eda/skill").then((r) => r.ok ? r.json() : null).catch(() => null),
      fetch("/eda/status").then((r) => r.ok ? r.json() : null).catch(() => null),
    ]).then(([tableData, skillData, statusData]) => {
      const filtered = (tableData || []).filter(
        (t) => !selectedTables || selectedTables.includes(t.name)
      );
      setTables(filtered);
      setSkillCount(skillData?.acronyms?.length ?? 0);
      if (statusData?.running) {
        setAnalyzing(true);
      }
    });
  }, [selectedTables]); // eslint-disable-line react-hooks/exhaustive-deps

  // ---------- manual trigger ----------

  const handleAnalyze = async () => {
    setAnalyzing(true);
    try {
      // POST is blocking — backend awaits the full EDA run before responding.
      // EDAProgress handles live feedback via SSE independently.
      await fetch("/eda/refresh", { method: "POST" });
    } catch {
      // Network error — EDAProgress will detect EDA stopping via SSE.
    }
    // Don't setAnalyzing(false) here — EDAProgress.onDone handles it.
  };

  // Called by EDAProgress when the "done" SSE event arrives.
  const handleAnalyzeDone = () => {
    setAnalyzing(false);
    fetchSkill();
  };

  // ---------- render ----------

  if (tables.length === 0) return null;

  return (
    <div className="w-full max-w-sm mx-auto mt-2 mb-5">
      {tables.map((table) => {
        const description = table.description_en;
        const hasStats = table.stats?.rows;

        return (
          <div
            key={table.name}
            className="bg-gray-900 border border-gray-800 rounded-2xl px-5 py-4 space-y-3"
          >
            {/* Table identity + stats */}
            <div className="flex items-start gap-3">
              <div className="min-w-0">
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-xs font-mono text-indigo-400 bg-indigo-950/50 border border-indigo-900/50 px-2 py-0.5 rounded">
                    {table.name}
                  </span>
                  {hasStats && (
                    <span className="text-xs text-emerald-500 flex items-center gap-1">
                      <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 inline-block" />
                      {t("welcome.dataReady")}
                    </span>
                  )}
                </div>
                <p className="text-xs text-gray-500 leading-relaxed">{description}</p>
                <button
                  onClick={onOpenContext}
                  className="mt-2 text-xs text-indigo-400/80 hover:text-indigo-300 transition-colors"
                >
                  {t("dataContext.openInWelcome")}
                </button>
              </div>
            </div>

            {/* Skill / EDA status section */}
            <div className="border-t border-gray-800 pt-3">
              {/* Still loading initial skill data */}
              {skillCount === null && !analyzing && (
                <span className="text-xs text-gray-600 animate-pulse">🧠 …</span>
              )}

              {/* EDA is running — live progress checklist via SSE */}
              {analyzing && (
                <EDAProgress onDone={handleAnalyzeDone} />
              )}

              {/* Abbreviations learned — badge links to SkillPanel */}
              {!analyzing && skillCount !== null && skillCount > 0 && (
                <button
                  onClick={onOpenSkill}
                  className="text-xs text-amber-500/80 hover:text-amber-400 transition-colors
                             flex items-center gap-1.5 group"
                >
                  <span>🧠</span>
                  <span className="group-hover:underline underline-offset-2">
                    {t("welcome.skillBadge", { count: skillCount })}
                  </span>
                  <span className="text-gray-600 group-hover:text-amber-500 transition-colors">→</span>
                </button>
              )}

              {/* No abbreviations yet — offer to trigger EDA */}
              {!analyzing && skillCount === 0 && (
                <div className="space-y-2">
                  <p className="text-xs text-gray-600 leading-relaxed">
                    {t("welcome.analyzeHint")}
                  </p>
                  <button
                    onClick={handleAnalyze}
                    className="text-xs bg-indigo-600/15 hover:bg-indigo-600/25
                               border border-indigo-600/30 hover:border-indigo-500/50
                               text-indigo-300 hover:text-indigo-200
                               rounded-lg px-3 py-1.5 flex items-center gap-1.5
                               transition-colors"
                  >
                    <span>🧠</span>
                    <span>{t("welcome.analyzeButton")}</span>
                  </button>
                </div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
