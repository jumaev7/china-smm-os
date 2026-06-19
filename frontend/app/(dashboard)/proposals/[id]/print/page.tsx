"use client";

import { useEffect } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { format, parseISO } from "date-fns";
import { salesProposalsApi } from "@/lib/api";
import { ErrorState, LoadingState } from "@/components/ui/PageStates";
import { useTranslation } from "@/lib/I18nProvider";

function formatMoney(amount: number, currency: string) {
  return new Intl.NumberFormat(undefined, { style: "currency", currency, maximumFractionDigits: 2 }).format(amount);
}

export default function ProposalPrintPage() {
  const { t } = useTranslation();
  const params = useParams();
  const id = params.id as string;

  const { data: p, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["sales-proposal", id],
    queryFn: () => salesProposalsApi.get(id).then((r) => r.data),
  });

  useEffect(() => {
    if (p) {
      const timer = setTimeout(() => window.print(), 400);
      return () => clearTimeout(timer);
    }
  }, [p]);

  if (isLoading) return <LoadingState message={t("commercialProposals.loading")} className="min-h-[50vh]" />;
  if (isError || !p) {
    return (
      <ErrorState
        message={error instanceof Error ? error.message : t("commercialProposals.loadError")}
        onRetry={() => refetch()}
      />
    );
  }

  return (
    <>
      <style jsx global>{`
        @media print {
          body * { visibility: hidden; }
          #print-root, #print-root * { visibility: visible; }
          #print-root { position: absolute; left: 0; top: 0; width: 100%; }
          .no-print { display: none !important; }
        }
      `}</style>

      <div className="no-print p-4 flex gap-3 bg-gray-50 border-b border-gray-200">
        <button type="button" onClick={() => window.print()} className="btn-primary text-sm">
          {t("commercialProposals.print")}
        </button>
        <Link href={`/proposals/${id}`} className="btn-secondary text-sm">
          {t("commercialProposals.backToDetail")}
        </Link>
      </div>

      <div id="print-root" className="max-w-3xl mx-auto p-8 space-y-6 text-gray-900">
        <header className="border-b-2 border-gray-900 pb-4 flex justify-between items-start">
          <div>
            <h1 className="text-2xl font-bold">{p.title}</h1>
            <p className="text-sm text-gray-600 font-mono mt-1">{p.proposal_number}</p>
          </div>
          <div className="text-right text-sm text-gray-600">
            <p>{t("commercialProposals.issueDate")}: {format(parseISO(p.issue_date), "MMMM d, yyyy")}</p>
            {p.valid_until && (
              <p>{t("commercialProposals.validUntil")}: {format(parseISO(p.valid_until), "MMMM d, yyyy")}</p>
            )}
          </div>
        </header>

        {p.customer_name && (
          <section>
            <p className="text-xs uppercase tracking-wider text-gray-500 font-semibold">{t("commercialProposals.customer")}</p>
            <p className="text-base font-medium mt-1">{p.customer_name}</p>
          </section>
        )}

        <table className="w-full text-sm border-collapse">
          <thead>
            <tr className="border-b-2 border-gray-300">
              <th className="text-left py-2 font-semibold">{t("commercialProposals.itemName")}</th>
              <th className="text-right py-2 font-semibold">{t("commercialProposals.quantity")}</th>
              <th className="text-right py-2 font-semibold">{t("commercialProposals.unitPrice")}</th>
              <th className="text-right py-2 font-semibold">{t("commercialProposals.itemTotal")}</th>
            </tr>
          </thead>
          <tbody>
            {p.items.map((item) => (
              <tr key={item.id} className="border-b border-gray-200">
                <td className="py-2.5">
                  <p className="font-medium">{item.product_or_service_name}</p>
                  {item.description && <p className="text-xs text-gray-500 mt-0.5">{item.description}</p>}
                </td>
                <td className="py-2.5 text-right">{item.quantity}</td>
                <td className="py-2.5 text-right">{formatMoney(item.unit_price, p.currency)}</td>
                <td className="py-2.5 text-right font-medium">{formatMoney(item.total, p.currency)}</td>
              </tr>
            ))}
          </tbody>
        </table>

        <div className="flex justify-end">
          <div className="w-72 space-y-1 text-sm">
            <div className="flex justify-between">
              <span>{t("commercialProposals.subtotal")}</span>
              <span>{formatMoney(p.subtotal, p.currency)}</span>
            </div>
            {p.discount > 0 && (
              <div className="flex justify-between text-gray-600">
                <span>{t("commercialProposals.proposalDiscount")}</span>
                <span>-{formatMoney(p.discount, p.currency)}</span>
              </div>
            )}
            {p.tax > 0 && (
              <div className="flex justify-between text-gray-600">
                <span>{t("commercialProposals.tax")}</span>
                <span>+{formatMoney(p.tax, p.currency)}</span>
              </div>
            )}
            <div className="flex justify-between font-bold text-lg pt-2 border-t-2 border-gray-900">
              <span>{t("commercialProposals.total")}</span>
              <span>{formatMoney(p.total, p.currency)}</span>
            </div>
          </div>
        </div>

        {p.notes && (
          <section>
            <p className="text-xs uppercase tracking-wider text-gray-500 font-semibold">{t("commercialProposals.notes")}</p>
            <p className="text-sm mt-1 whitespace-pre-wrap">{p.notes}</p>
          </section>
        )}

        {p.terms && (
          <section>
            <p className="text-xs uppercase tracking-wider text-gray-500 font-semibold">{t("commercialProposals.terms")}</p>
            <p className="text-sm mt-1 whitespace-pre-wrap">{p.terms}</p>
          </section>
        )}

        <footer className="text-xs text-gray-400 pt-8 border-t border-gray-200 text-center">
          {t("commercialProposals.printFooter")}
        </footer>
      </div>
    </>
  );
}
