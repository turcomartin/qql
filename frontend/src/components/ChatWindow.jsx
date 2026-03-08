import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import MessageBubble from "./MessageBubble";
import WelcomeCard from "./WelcomeCard";

export default function ChatWindow({
  messages,
  onSend,
  onClear,
  onOpenSkill,
  onOpenContext,
  selectedTables = [],
}) {
  const { t } = useTranslation();
  const bottomRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  if (messages.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center text-gray-500 overflow-y-auto px-4 py-8">
        <div className="text-center w-full max-w-sm">
          <div className="text-4xl mb-4">📊</div>
          <p className="text-xl font-semibold text-gray-200 mb-5">
            {t("welcome.title")}
          </p>
          <WelcomeCard
            selectedTables={selectedTables}
            onOpenSkill={onOpenSkill}
            onOpenContext={onOpenContext}
          />
          <p className="text-sm text-gray-500 mt-2">
            {t("welcome.hint")}
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto px-4 py-6">
      <div className="max-w-4xl mx-auto">
        {messages.map((msg) => (
          <MessageBubble key={msg.id} message={msg} onSend={onSend} onClear={onClear} />
        ))}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
