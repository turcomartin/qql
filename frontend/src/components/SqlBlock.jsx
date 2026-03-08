import { useEffect, useRef, useState } from "react";

export default function SqlBlock({ sql }) {
  const codeRef = useRef(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (codeRef.current && window.Prism) {
      window.Prism.highlightElement(codeRef.current);
    }
  }, [sql]);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(sql);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="relative mt-2 group">
      <pre className="!my-0 overflow-x-auto">
        <code ref={codeRef} className="language-sql">
          {sql}
        </code>
      </pre>
      <button
        onClick={handleCopy}
        className="absolute top-2 right-2 px-2 py-1 text-xs rounded bg-gray-700 text-gray-300
                   opacity-0 group-hover:opacity-100 transition-opacity hover:bg-gray-600"
      >
        {copied ? "Copied!" : "Copy"}
      </button>
    </div>
  );
}
