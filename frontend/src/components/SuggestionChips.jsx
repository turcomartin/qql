import { useEffect, useState } from "react";

/**
 * Clickable suggestion chips shown above the input bar.
 * Fetches example queries from the /tables endpoint and rotates 3 at a time.
 * Clicking a chip calls onSend(query) immediately.
 */
export default function SuggestionChips({ selectedTables, onSend, disabled }) {
  const [chips, setChips] = useState([]);

  useEffect(() => {
    fetch("/tables")
      .then((r) => r.json())
      .then((tables) => {
        const allChips = tables
          .filter((t) => !selectedTables || selectedTables.includes(t.name))
          .flatMap((t) => t.example_queries?.en || []);
        // Shuffle and pick up to 3
        const shuffled = allChips.sort(() => Math.random() - 0.5);
        setChips(shuffled.slice(0, 3));
      })
      .catch(() => {
        // Silently fail — chips are non-critical
        setChips([]);
      });
  }, [selectedTables]);

  if (chips.length === 0) return null;

  return (
    <div className="flex flex-wrap gap-2 px-4 pb-2 max-w-4xl mx-auto">
      {chips.map((chip, i) => (
        <button
          key={i}
          onClick={() => !disabled && onSend(chip)}
          disabled={disabled}
          className="text-xs bg-gray-800 hover:bg-gray-700 text-gray-400 hover:text-gray-200
                     px-3 py-1.5 rounded-full border border-gray-700 hover:border-gray-600
                     transition-all disabled:opacity-40 disabled:cursor-not-allowed truncate max-w-xs"
          title={chip}
        >
          {chip}
        </button>
      ))}
    </div>
  );
}
