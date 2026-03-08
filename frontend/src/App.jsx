import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";


import ChatWindow from "./components/ChatWindow";
import DataContextModal from "./components/DataContextModal";
import InputBar from "./components/InputBar";
import ModeToggle from "./components/ModeToggle";
import OnboardingFlow from "./components/OnboardingFlow";
import SkillPanel from "./components/SkillPanel";
import SuggestionChips from "./components/SuggestionChips";
import { useChat } from "./hooks/useChat";

export default function App() {
  const { t } = useTranslation();

  // Load persisted preferences
  const [onboarded, setOnboarded] = useState(
    () => localStorage.getItem("qql_onboarded") === "true"
  );
  const [selectedTables, setSelectedTables] = useState(
    () => JSON.parse(localStorage.getItem("qql_tables") || '["sales"]')
  );

  const [skillPanelOpen, setSkillPanelOpen] = useState(false);
  const [dataContextOpen, setDataContextOpen] = useState(false);
  // Skill count shown as a badge on the header 🧠 button.
  // Fetched on mount and refreshed whenever the panel closes (user may have edited).
  const [headerSkillCount, setHeaderSkillCount] = useState(null);

  const refreshHeaderSkillCount = useCallback(() => {
    fetch("/eda/skill")
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => setHeaderSkillCount(data?.acronyms?.length ?? 0))
      .catch(() => setHeaderSkillCount(0));
  }, []);

  useEffect(() => {
    refreshHeaderSkillCount();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Re-fetch badge count whenever skill panel closes (catches edits & re-inference).
  useEffect(() => {
    if (!skillPanelOpen) refreshHeaderSkillCount();
  }, [skillPanelOpen, refreshHeaderSkillCount]);

  const { messages, isStreaming, mode, setMode, sendMessage, stopStreaming, clearChat } =
    useChat({ selectedTables });

  const handleOnboardingComplete = useCallback(({ tables }) => {
    setSelectedTables(tables);
    setOnboarded(true);
  }, []);

  const reopenOnboarding = useCallback(() => {
    localStorage.removeItem("qql_onboarded");
    setOnboarded(false);
  }, []);

  if (!onboarded) {
    return <OnboardingFlow onComplete={handleOnboardingComplete} />;
  }

  return (
    <div className="h-full flex flex-col bg-gray-950 text-gray-100">
      {/* Header */}
      <header className="flex items-center justify-between px-4 py-3 border-b border-gray-800 bg-gray-950 flex-shrink-0">
        <div className="flex items-center gap-3">
          <span className="text-indigo-400 font-bold text-lg tracking-tight">{t("appName")}</span>
          <span className="text-gray-500 text-sm hidden sm:inline">{t("appSubtitle")}</span>
          {selectedTables.length > 0 && (
            <button
              onClick={reopenOnboarding}
              title={t("settings")}
              className="text-xs bg-gray-800 text-gray-400 px-2 py-0.5 rounded-full border border-gray-700
                         hover:border-indigo-500 hover:text-indigo-300 transition-colors"
            >
              {selectedTables.join(", ")}
            </button>
          )}
        </div>
        <div className="flex items-center gap-2">
          <ModeToggle mode={mode} onChange={setMode} />
          {/* Data context modal toggle */}
          <button
            onClick={() => setDataContextOpen(true)}
            className={`text-gray-500 hover:text-indigo-400 transition-colors p-1 text-base leading-none
                        ${dataContextOpen ? "text-indigo-400" : ""}`}
            title={t("dataContext.title")}
          >
            📘
          </button>
          {/* Skill panel toggle */}
          <button
            onClick={() => setSkillPanelOpen(true)}
            className={`relative text-gray-500 hover:text-indigo-400 transition-colors p-1 text-base leading-none
                        ${skillPanelOpen ? "text-indigo-400" : ""}`}
            title={t("skill.title")}
          >
            🧠
            {headerSkillCount !== null && headerSkillCount > 0 && (
              <span
                className="absolute -top-0.5 -right-0.5 min-w-[14px] h-[14px] px-0.5
                           bg-indigo-600 text-white text-[9px] font-bold rounded-full
                           flex items-center justify-center leading-none pointer-events-none"
              >
                {headerSkillCount > 99 ? "99+" : headerSkillCount}
              </span>
            )}
          </button>
          <button
            onClick={reopenOnboarding}
            className="text-gray-500 hover:text-gray-300 transition-colors p-1"
            title={t("settings")}
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
            </svg>
          </button>
          {messages.length > 0 && (
            <button
              onClick={clearChat}
              disabled={isStreaming}
              className="text-xs text-gray-500 hover:text-gray-300 transition-colors disabled:opacity-50"
            >
              {t("clear")}
            </button>
          )}
        </div>
      </header>

      {/* Mode hint */}
      {mode === "oneshot" && (
        <div className="px-4 py-1 bg-amber-950/40 border-b border-amber-900/40 text-xs text-amber-400 text-center">
          {t("oneShotBanner")}
        </div>
      )}

      {/* Chat area */}
      <ChatWindow
        messages={messages}
        onSend={sendMessage}
        onClear={clearChat}
        onOpenSkill={() => setSkillPanelOpen(true)}
        onOpenContext={() => setDataContextOpen(true)}
        selectedTables={selectedTables}
      />

      {/* Suggestion chips */}
      <SuggestionChips
        selectedTables={selectedTables}
        onSend={sendMessage}
        disabled={isStreaming}
      />

      {/* Input */}
      <InputBar onSend={sendMessage} isStreaming={isStreaming} onStop={stopStreaming} />

      {/* Skill panel */}
      {skillPanelOpen && (
        <SkillPanel onClose={() => setSkillPanelOpen(false)} />
      )}

      {/* Data context modal */}
      {dataContextOpen && (
        <DataContextModal onClose={() => setDataContextOpen(false)} />
      )}
    </div>
  );
}
