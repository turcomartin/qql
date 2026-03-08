import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";


/**
 * Full-screen onboarding overlay — shown on first visit.
 *
 * Step 1: Table selection with EDA-derived descriptions
 *
 * Saves preferences to localStorage and calls onComplete({language, tables}).
 */
export default function OnboardingFlow({ onComplete }) {
  const { t } = useTranslation();
  const [tables, setTables] = useState([]);
  const [availableTables, setAvailableTables] = useState([]);
  const [loadingTables, setLoadingTables] = useState(false);

  useEffect(() => {
    if (availableTables.length === 0) {
      setLoadingTables(true);
      fetch("/tables")
        .then((r) => r.json())
        .then((data) => {
          setAvailableTables(data);
          // Pre-select all tables
          setTables(data.map((t) => t.name));
        })
        .catch(() => {
          // Fallback: use default sales table
          setAvailableTables([{
            name: "sales",
            label_en: "Sales Records",
            label_es: "Registros de Ventas",
            description_en: "Sales transaction data",
            description_es: "Datos de transacciones de ventas",
            stats: {},
            example_queries: { en: [], es: [] },
          }]);
          setTables(["sales"]);
        })
        .finally(() => setLoadingTables(false));
    }
  }, [availableTables.length]);

  const toggleTable = (name) => {
    setTables((prev) =>
      prev.includes(name) ? prev.filter((t) => t !== name) : [...prev, name]
    );
  };

  const finish = () => {
    const selectedTables = tables.length > 0 ? tables : ["sales"];
    localStorage.setItem("qql_tables", JSON.stringify(selectedTables));
    localStorage.setItem("qql_onboarded", "true");
    onComplete({ tables: selectedTables });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-gray-950">
      <div className="w-full max-w-lg px-6 py-8">
        <Step2
          t={t}
          availableTables={availableTables}
          loading={loadingTables}
          selectedTables={tables}
          onToggle={toggleTable}
          onFinish={finish}
        />
      </div>
    </div>
  );
}
function Step2({ t, availableTables, loading, selectedTables, onToggle, onFinish }) {
  return (
    <div className="space-y-6">
      <div className="text-center">
        <h2 className="text-2xl font-bold text-gray-100">{t("onboarding.step2Title")}</h2>
        <p className="text-gray-400 text-sm mt-1">{t("onboarding.step2Subtitle")}</p>
      </div>

      {loading ? (
        <div className="text-center text-gray-500 py-8">
          <div className="animate-spin w-6 h-6 border-2 border-indigo-500 border-t-transparent rounded-full mx-auto mb-2" />
          Loading…
        </div>
      ) : (
        <div className="space-y-3">
          {availableTables.map((table) => (
            <TableCard
              key={table.name}
              table={table}
              selected={selectedTables.includes(table.name)}
              onToggle={() => onToggle(table.name)}
            />
          ))}
        </div>
      )}

      <button
        onClick={onFinish}
        disabled={selectedTables.length === 0}
        className="w-full py-3 rounded-xl bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white font-semibold transition-colors"
      >
        {t("onboarding.letsGo")}
      </button>
    </div>
  );
}

function TableCard({ table, selected, onToggle }) {
  const label = table.label_en;
  const description = table.description_en;
  const examples = table.example_queries?.en || [];

  return (
    <button
      onClick={onToggle}
      className={`w-full text-left p-4 rounded-2xl border-2 transition-all ${
        selected
          ? "border-indigo-500 bg-indigo-950/40"
          : "border-gray-700 bg-gray-900 hover:border-gray-600"
      }`}
    >
      <div className="flex items-start gap-3">
        <div className={`mt-0.5 w-5 h-5 rounded flex-shrink-0 border-2 flex items-center justify-center ${
          selected ? "border-indigo-500 bg-indigo-500" : "border-gray-600"
        }`}>
          {selected && (
            <svg className="w-3 h-3 text-white" fill="currentColor" viewBox="0 0 12 12">
              <path d="M10 3L5 8.5 2 5.5" stroke="currentColor" strokeWidth="1.5" fill="none" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
          )}
        </div>
        <div className="flex-1 min-w-0">
          <p className="font-semibold text-gray-100">{label}</p>
          <p className="text-sm text-gray-400 mt-0.5">{description}</p>
          {examples.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1">
              {examples.slice(0, 2).map((ex, i) => (
                <span key={i} className="text-xs bg-gray-800 text-gray-400 px-2 py-0.5 rounded-full">
                  "{ex}"
                </span>
              ))}
            </div>
          )}
        </div>
      </div>
    </button>
  );
}
