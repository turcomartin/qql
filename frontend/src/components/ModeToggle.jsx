import { useTranslation } from "react-i18next";

export default function ModeToggle({ mode, onChange }) {
  const { t } = useTranslation();

  return (
    <div className="flex items-center gap-1 bg-gray-800 rounded-lg p-1 text-xs font-medium">
      <button
        onClick={() => onChange("conversational")}
        className={`px-3 py-1 rounded-md transition-colors ${
          mode === "conversational"
            ? "bg-indigo-600 text-white"
            : "text-gray-400 hover:text-gray-200"
        }`}
      >
        {t("mode.conversational")}
      </button>
      <button
        onClick={() => onChange("oneshot")}
        className={`px-3 py-1 rounded-md transition-colors ${
          mode === "oneshot"
            ? "bg-indigo-600 text-white"
            : "text-gray-400 hover:text-gray-200"
        }`}
      >
        {t("mode.oneshot")}
      </button>
    </div>
  );
}
