"use client";

import { useState } from "react";
import Link from "next/link";
import { useMutation, useQuery } from "@tanstack/react-query";
import { ArrowLeft, FileSpreadsheet, Loader2, Upload } from "lucide-react";
import toast from "react-hot-toast";
import { clientsApi, Client, productsApi, ProductImportSource, normalizeList } from "@/lib/api";

export default function ProductImportPage() {
  const [clientId, setClientId] = useState("");
  const [sourceType, setSourceType] = useState<ProductImportSource>("csv");
  const [file, setFile] = useState<File | null>(null);
  const [catalogText, setCatalogText] = useState("");

  const { data: clientsData } = useQuery({
    queryKey: ["clients"],
    queryFn: () => clientsApi.list({ limit: 200 }).then((r) => r.data),
  });
  const clientOptions = normalizeList<Client>(clientsData);

  const importMutation = useMutation({
    mutationFn: () => {
      const fd = new FormData();
      fd.append("client_id", clientId);
      fd.append("source_type", sourceType);
      if (sourceType === "text") {
        fd.append("catalog_text", catalogText);
      } else if (file) {
        fd.append("file", file);
      }
      return productsApi.import(fd).then((r) => r.data);
    },
    onSuccess: (result) => {
      toast.success(`Imported ${result.imported} product(s)`);
      if (result.errors.length > 0) {
        toast.error(`${result.errors.length} warning(s) — check import log`);
      }
    },
    onError: (err: Error) => toast.error(err.message || "Import failed"),
  });

  const needsFile = sourceType !== "text";

  return (
    <div className="p-6 max-w-2xl mx-auto space-y-6">
      <div>
        <Link href="/products" className="text-xs text-brand-700 hover:text-brand-900 inline-flex items-center gap-1 mb-2">
          <ArrowLeft size={12} />
          Back to products
        </Link>
        <h1 className="text-xl font-semibold text-gray-900 flex items-center gap-2">
          <FileSpreadsheet size={22} className="text-brand-600" />
          Product Import
        </h1>
        <p className="text-sm text-gray-500 mt-1">
          Bulk import from CSV/Excel or AI extraction from PDF/text catalogs
        </p>
      </div>

      <div className="card p-4 space-y-4">
        <label className="block space-y-1 text-sm">
          <span className="text-gray-600">Client</span>
          <select className="input w-full" value={clientId} onChange={(e) => setClientId(e.target.value)}>
            <option value="">Select client</option>
            {clientOptions.map((c) => (
              <option key={c.id} value={c.id}>
                {c.company_name}
              </option>
            ))}
          </select>
        </label>

        <label className="block space-y-1 text-sm">
          <span className="text-gray-600">Source type</span>
          <select
            className="input w-full"
            value={sourceType}
            onChange={(e) => setSourceType(e.target.value as ProductImportSource)}
          >
            <option value="csv">CSV</option>
            <option value="xlsx">Excel (.xlsx)</option>
            <option value="pdf">PDF (AI extraction)</option>
            <option value="text">Text catalog (AI extraction)</option>
          </select>
        </label>

        {needsFile ? (
          <label className="block space-y-1 text-sm">
            <span className="text-gray-600">File</span>
            <input
              type="file"
              className="input w-full text-sm"
              accept={
                sourceType === "csv"
                  ? ".csv"
                  : sourceType === "xlsx"
                    ? ".xlsx,.xls"
                    : ".pdf"
              }
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
            <p className="text-[10px] text-gray-400">
              CSV/Excel columns: name, sku, category, description, moq, unit_price, currency
            </p>
          </label>
        ) : (
          <label className="block space-y-1 text-sm">
            <span className="text-gray-600">Catalog text</span>
            <textarea
              className="input w-full min-h-[160px] text-sm font-mono"
              placeholder="Paste supplier catalog, product list, or spec sheet text…"
              value={catalogText}
              onChange={(e) => setCatalogText(e.target.value)}
            />
          </label>
        )}

        <button
          type="button"
          className="btn-primary flex items-center gap-2"
          disabled={
            !clientId ||
            importMutation.isPending ||
            (needsFile ? !file : !catalogText.trim())
          }
          onClick={() => importMutation.mutate()}
        >
          {importMutation.isPending ? (
            <Loader2 size={16} className="animate-spin" />
          ) : (
            <Upload size={16} />
          )}
          Run import
        </button>

        {importMutation.data && (
          <div className="rounded-lg border border-gray-100 bg-gray-50 p-3 text-xs space-y-1">
            <p>
              Status: <span className="font-medium">{importMutation.data.job.status}</span>
            </p>
            <p>Imported: {importMutation.data.imported}</p>
            <p>Skipped: {importMutation.data.skipped}</p>
            {importMutation.data.errors.length > 0 && (
              <ul className="text-amber-700 list-disc pl-4 mt-2">
                {importMutation.data.errors.slice(0, 5).map((e) => (
                  <li key={e}>{e}</li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
