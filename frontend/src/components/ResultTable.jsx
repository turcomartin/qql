export default function ResultTable({ columns, rows, row_count, truncated }) {
  if (!columns || columns.length === 0) {
    return (
      <p className="text-sm text-gray-400 mt-2 italic">Query returned no rows.</p>
    );
  }

  return (
    <div className="mt-3">
      <div className="overflow-x-auto rounded-lg border border-gray-700">
        <table className="min-w-full text-sm text-left">
          <thead className="bg-gray-800 text-gray-300 uppercase text-xs tracking-wider">
            <tr>
              {columns.map((col) => (
                <th key={col} className="px-4 py-2 font-medium whitespace-nowrap">
                  {col}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-800">
            {rows.map((row, ri) => (
              <tr key={ri} className="hover:bg-gray-800/50 transition-colors">
                {row.map((cell, ci) => (
                  <td
                    key={ci}
                    className="px-4 py-2 text-gray-200 whitespace-nowrap max-w-xs truncate"
                    title={cell ?? ""}
                  >
                    {cell ?? <span className="text-gray-500 italic">null</span>}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-gray-500 mt-1">
        {truncated
          ? `Showing first ${rows.length} of ${row_count} rows`
          : `${row_count} row${row_count !== 1 ? "s" : ""}`}
      </p>
    </div>
  );
}
