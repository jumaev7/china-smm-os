"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState, useEffect } from "react";
import { useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { format, parseISO } from "date-fns";
import {
  Users,
  X,
  Sparkles,
  Plus,
  Phone,
  Mail,
  MessageCircle,
  Clock,
  DollarSign,
  Loader2,
  Bot,
  Copy,
  Check,
  FileText,
  Pencil,
  Save,
  Briefcase,
  Send,
  ClipboardList,
} from "lucide-react";
import toast from "react-hot-toast";
import { ProductMatchPanel } from "@/components/products/ProductMatchPanel";
import { PartnerMatchPanel } from "@/components/partners/PartnerMatchPanel";
import {
  clientsApi,
  Client,
  crmApi,
  proposalsApi,
  outreachApi,
  salesPlaybooksApi,
  productsApi,
  SalesPlaybook,
  attributionLinksApi,
  CrmLead,
  CrmActivity,
  CrmActivityType,
  CrmExtractResult,
  CrmAiSuggestNextStep,
  CrmAiGeneratedMessage,
  CrmProposal,
  ProposalStatus,
  ProposalDocumentStatus,
  OutreachStatus,
  CrmDocument,
  DocumentType,
  DocumentStatus,
  LeadStatus,
  LeadPriority,
  MessagePurpose,
  LeadInsights,
  QualificationLevel,
  leadIntelligenceApi,
  LeadClassification,
  BuyerClassification,
  buyerIntelligenceApi,
  normalizeList,
  dealRoomApi,
} from "@/lib/api";
import { cn, INBOX_PRIORITY_CONFIG } from "@/lib/utils";
import { useTranslation } from "@/lib/I18nProvider";
import {
  EmptyState,
  ErrorState,
  LoadingState,
  PartialErrorsBanner,
} from "@/components/ui/PageStates";

const PIPELINE_COLUMNS: { status: LeadStatus; label: string; color: string }[] = [
  { status: "new", label: "New", color: "border-sky-200 bg-sky-50/50" },
  { status: "contacted", label: "Contacted", color: "border-indigo-200 bg-indigo-50/50" },
  { status: "qualified", label: "Qualified", color: "border-violet-200 bg-violet-50/50" },
  { status: "proposal_sent", label: "Proposal Sent", color: "border-amber-200 bg-amber-50/50" },
  { status: "negotiation", label: "Negotiation", color: "border-orange-200 bg-orange-50/50" },
  { status: "won", label: "Won", color: "border-emerald-200 bg-emerald-50/50" },
  { status: "lost", label: "Lost", color: "border-gray-200 bg-gray-50/50" },
];

const ACTIVITY_TYPES: { value: CrmActivityType; label: string }[] = [
  { value: "note", label: "Note" },
  { value: "call", label: "Call" },
  { value: "message", label: "Message" },
  { value: "meeting", label: "Meeting" },
  { value: "proposal", label: "Proposal" },
  { value: "follow_up", label: "Follow-up" },
];

function formatValue(val: number | string | null | undefined): string | null {
  if (val == null || val === "") return null;
  const n = typeof val === "string" ? parseFloat(val) : val;
  if (Number.isNaN(n)) return String(val);
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(n);
}

function scoreBadgeLabel(score?: number | null, level?: QualificationLevel | null): string | null {
  if (score == null) return null;
  const emoji =
    score >= 70 || level === "hot" || level === "qualified" || level === "opportunity"
      ? "🔥"
      : score >= 40 || level === "warm"
        ? "🟡"
        : "⚪";
  return `${score} ${emoji}`;
}

const CLASSIFICATION_BADGE: Record<LeadClassification, string> = {
  hot: "bg-red-50 border-red-200 text-red-800",
  qualified: "bg-violet-50 border-violet-200 text-violet-800",
  nurturing: "bg-emerald-50 border-emerald-200 text-emerald-800",
  cold: "bg-sky-50 border-sky-200 text-sky-800",
  inactive: "bg-gray-50 border-gray-200 text-gray-600",
};

const BUYER_CLASS_LABELS: Record<BuyerClassification, string> = {
  hot_buyer: "Hot",
  strategic_buyer: "Strategic",
  high_potential_buyer: "High pot.",
  active_buyer: "Active",
  inactive_buyer: "Inactive",
  price_sensitive_buyer: "Price sens.",
  at_risk_buyer: "At risk",
};

const BUYER_CLASS_BADGE: Record<BuyerClassification, string> = {
  hot_buyer: "bg-red-50 border-red-200 text-red-800",
  strategic_buyer: "bg-indigo-50 border-indigo-200 text-indigo-800",
  high_potential_buyer: "bg-violet-50 border-violet-200 text-violet-800",
  active_buyer: "bg-emerald-50 border-emerald-200 text-emerald-800",
  inactive_buyer: "bg-gray-50 border-gray-200 text-gray-600",
  price_sensitive_buyer: "bg-amber-50 border-amber-200 text-amber-800",
  at_risk_buyer: "bg-orange-50 border-orange-200 text-orange-800",
};

function LeadCard({
  lead,
  classification,
  classificationScore,
  buyerClassification,
  buyerScore,
  onClick,
}: {
  lead: CrmLead;
  classification?: LeadClassification | null;
  classificationScore?: number | null;
  buyerClassification?: BuyerClassification | null;
  buyerScore?: number | null;
  onClick: () => void;
}) {
  const priorityCfg = INBOX_PRIORITY_CONFIG[lead.priority];
  const value = formatValue(lead.estimated_value);

  return (
    <button
      type="button"
      onClick={onClick}
      className="card p-2.5 w-full text-left hover:ring-1 hover:ring-brand-200 transition-shadow"
    >
      <div className="flex items-start justify-between gap-1">
        <div className="min-w-0">
          <p className="text-xs font-semibold text-gray-900 truncate">{lead.name}</p>
          {lead.company && (
            <p className="text-[10px] text-gray-500 truncate">{lead.company}</p>
          )}
        </div>
        <span
          className={cn(
            "text-[9px] px-1.5 py-0.5 rounded-full border font-medium shrink-0 capitalize",
            priorityCfg.color,
          )}
        >
          {lead.priority}
        </span>
        {(buyerScore != null || classificationScore != null || lead.lead_score != null) && (
          <span className="text-[9px] px-1.5 py-0.5 rounded-full bg-orange-50 border border-orange-200 text-orange-900 font-semibold shrink-0 tabular-nums">
            {buyerScore ?? classificationScore ?? lead.lead_score}
          </span>
        )}
        {buyerClassification && (
          <span
            className={cn(
              "text-[9px] px-1.5 py-0.5 rounded-full border font-medium shrink-0",
              BUYER_CLASS_BADGE[buyerClassification],
            )}
          >
            {BUYER_CLASS_LABELS[buyerClassification]}
          </span>
        )}
        {classification && !buyerClassification && (
          <span
            className={cn(
              "text-[9px] px-1.5 py-0.5 rounded-full border font-medium shrink-0 capitalize",
              CLASSIFICATION_BADGE[classification],
            )}
          >
            {classification}
          </span>
        )}
      </div>
      {lead.interest && (
        <p className="text-[10px] text-gray-600 mt-1 line-clamp-2">{lead.interest}</p>
      )}
      <div className="flex flex-wrap gap-1.5 mt-1.5 text-[9px] text-gray-500">
        {value && (
          <span className="inline-flex items-center gap-0.5">
            <DollarSign size={9} /> {value}
          </span>
        )}
        {lead.next_follow_up_at && (
          <span className="inline-flex items-center gap-0.5 text-orange-700">
            <Clock size={9} />
            {format(parseISO(lead.next_follow_up_at), "MMM d")}
          </span>
        )}
      </div>
    </button>
  );
}

const PROPOSAL_STATUS_STYLE: Record<ProposalStatus, string> = {
  draft: "bg-gray-100 text-gray-700 border-gray-200",
  sent: "bg-sky-100 text-sky-800 border-sky-200",
  accepted: "bg-emerald-100 text-emerald-800 border-emerald-200",
  rejected: "bg-red-100 text-red-800 border-red-200",
};

const V2_PROPOSAL_STATUS_STYLE: Record<ProposalDocumentStatus, string> = {
  draft: "bg-gray-100 text-gray-700 border-gray-200",
  reviewed: "bg-violet-100 text-violet-800 border-violet-200",
  sent: "bg-sky-100 text-sky-800 border-sky-200",
  accepted: "bg-emerald-100 text-emerald-800 border-emerald-200",
  rejected: "bg-red-100 text-red-800 border-red-200",
};

const OUTREACH_STATUS_STYLE: Record<OutreachStatus, string> = {
  draft: "bg-gray-100 text-gray-700 border-gray-200",
  approved: "bg-emerald-100 text-emerald-800 border-emerald-200",
  sent: "bg-sky-100 text-sky-800 border-sky-200",
  archived: "bg-gray-100 text-gray-500 border-gray-200",
};

const DOCUMENT_STATUS_STYLE: Record<DocumentStatus, string> = {
  draft: "bg-gray-100 text-gray-700 border-gray-200",
  sent: "bg-sky-100 text-sky-800 border-sky-200",
  signed: "bg-violet-100 text-violet-800 border-violet-200",
  paid: "bg-emerald-100 text-emerald-800 border-emerald-200",
  canceled: "bg-red-100 text-red-800 border-red-200",
};

function DocumentsSection({
  proposalId,
  proposalStatus,
  language,
}: {
  proposalId: string;
  proposalStatus: ProposalStatus;
  language: string;
}) {
  const queryClient = useQueryClient();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [editText, setEditText] = useState("");
  const [copied, setCopied] = useState(false);

  const { data: documentsData, isLoading } = useQuery({
    queryKey: ["crm-documents", proposalId],
    queryFn: () => crmApi.listDocuments(proposalId).then((r) => r.data),
  });

  const documents = normalizeList<CrmDocument>(documentsData);
  const active =
    documents.find((d) => d.id === selectedId) ?? documents[0] ?? null;

  const generateMutation = useMutation({
    mutationFn: (document_type: DocumentType) =>
      crmApi
        .generateDocument(proposalId, { document_type, language: language || "ru" })
        .then((r) => r.data),
    onSuccess: (doc) => {
      setSelectedId(doc.id);
      setEditing(false);
      queryClient.invalidateQueries({ queryKey: ["crm-documents", proposalId] });
      toast.success("Document generated — review before signing");
    },
    onError: (err: Error) => toast.error(err.message || "Generation failed"),
  });

  const updateMutation = useMutation({
    mutationFn: (data: Parameters<typeof crmApi.updateDocument>[1]) =>
      crmApi.updateDocument(active!.id, data).then((r) => r.data),
    onSuccess: (doc) => {
      setSelectedId(doc.id);
      setEditing(false);
      queryClient.invalidateQueries({ queryKey: ["crm-documents", proposalId] });
      toast.success("Document updated");
    },
    onError: (err: Error) => toast.error(err.message || "Update failed"),
  });

  const markStatus = (status: DocumentStatus) => {
    if (!active) return;
    updateMutation.mutate({ status });
  };

  const copyDocument = async () => {
    if (!active) return;
    await navigator.clipboard.writeText(active.document_text);
    setCopied(true);
    toast.success("Copied to clipboard");
    setTimeout(() => setCopied(false), 2000);
  };

  const startEdit = () => {
    if (!active) return;
    setEditText(active.document_text);
    setEditing(true);
  };

  const saveEdit = () => {
    if (!active || !editText.trim()) return;
    updateMutation.mutate({ document_text: editText.trim() });
  };

  const canGenerate = proposalStatus === "accepted";

  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50/50 p-2.5 space-y-2 mt-2">
      <div className="flex items-center justify-between gap-2">
        <p className="text-[11px] font-semibold text-amber-950 flex items-center gap-1.5">
          <FileText size={12} />
          Documents
        </p>
        <div className="flex gap-1">
          <button
            type="button"
            disabled={!canGenerate || generateMutation.isPending}
            onClick={() => generateMutation.mutate("contract")}
            className="text-[10px] px-2 py-0.5 rounded border border-amber-300 bg-white text-amber-900 hover:bg-amber-100 disabled:opacity-50 flex items-center gap-1"
            title={canGenerate ? undefined : "Mark proposal as accepted first"}
          >
            {generateMutation.isPending ? (
              <Loader2 size={10} className="animate-spin" />
            ) : (
              <Sparkles size={10} />
            )}
            Contract
          </button>
          <button
            type="button"
            disabled={!canGenerate || generateMutation.isPending}
            onClick={() => generateMutation.mutate("invoice")}
            className="text-[10px] px-2 py-0.5 rounded border border-amber-300 bg-white text-amber-900 hover:bg-amber-100 disabled:opacity-50 flex items-center gap-1"
            title={canGenerate ? undefined : "Mark proposal as accepted first"}
          >
            Invoice
          </button>
        </div>
      </div>

      {!canGenerate && (
        <p className="text-[10px] text-amber-800/80">
          Accept the proposal to generate contract or invoice drafts.
        </p>
      )}

      {isLoading && <p className="text-[11px] text-gray-400">Loading…</p>}

      {!isLoading && documents.length === 0 && canGenerate && (
        <p className="text-[11px] text-amber-800/70">No documents yet — generate a draft.</p>
      )}

      {documents.length > 1 && (
        <select
          className="input w-full text-xs"
          value={active?.id ?? ""}
          onChange={(e) => {
            setSelectedId(e.target.value);
            setEditing(false);
          }}
        >
          {documents.map((d) => (
            <option key={d.id} value={d.id}>
              {d.title} · {d.document_type} · {d.status}
            </option>
          ))}
        </select>
      )}

      {active && (
        <div className="rounded border border-amber-200 bg-white p-2 space-y-2">
          <div className="flex items-start justify-between gap-2">
            <div>
              <p className="text-xs font-semibold text-gray-900 leading-snug">{active.title}</p>
              <p className="text-[10px] text-gray-500 capitalize">{active.document_type}</p>
            </div>
            <span
              className={cn(
                "text-[9px] px-1.5 py-0.5 rounded-full border font-medium capitalize shrink-0",
                DOCUMENT_STATUS_STYLE[active.status],
              )}
            >
              {active.status}
            </span>
          </div>

          {active.amount != null && (
            <p className="text-[10px] text-gray-600">
              {Number(active.amount).toLocaleString()} {active.currency}
              {active.due_date && ` · due ${format(parseISO(active.due_date), "MMM d, yyyy")}`}
            </p>
          )}

          {editing ? (
            <textarea
              className="input w-full text-[11px] min-h-[180px] font-mono"
              value={editText}
              onChange={(e) => setEditText(e.target.value)}
            />
          ) : (
            <div className="rounded bg-gray-50 p-2 text-[11px] text-gray-800 max-h-40 overflow-y-auto whitespace-pre-wrap font-mono leading-relaxed">
              {active.document_text}
            </div>
          )}

          <div className="flex flex-wrap gap-1">
            {editing ? (
              <>
                <button
                  type="button"
                  disabled={updateMutation.isPending}
                  onClick={saveEdit}
                  className="text-[10px] px-2 py-0.5 rounded border border-amber-300 bg-amber-50 flex items-center gap-1"
                >
                  <Save size={10} /> Save
                </button>
                <button
                  type="button"
                  onClick={() => setEditing(false)}
                  className="text-[10px] px-2 py-0.5 rounded border border-gray-200"
                >
                  Cancel
                </button>
              </>
            ) : (
              <>
                <button
                  type="button"
                  onClick={copyDocument}
                  className="text-[10px] px-2 py-0.5 rounded border border-gray-200 flex items-center gap-1"
                >
                  {copied ? <Check size={10} /> : <Copy size={10} />}
                  Copy
                </button>
                <button
                  type="button"
                  onClick={startEdit}
                  className="text-[10px] px-2 py-0.5 rounded border border-gray-200 flex items-center gap-1"
                >
                  <Pencil size={10} /> Edit
                </button>
              </>
            )}
            {active.status === "draft" && (
              <button
                type="button"
                disabled={updateMutation.isPending}
                onClick={() => markStatus("sent")}
                className="text-[10px] px-2 py-0.5 rounded border border-sky-200 bg-sky-50 text-sky-800"
              >
                Mark sent
              </button>
            )}
            {active.status === "sent" && active.document_type === "contract" && (
              <button
                type="button"
                disabled={updateMutation.isPending}
                onClick={() => markStatus("signed")}
                className="text-[10px] px-2 py-0.5 rounded border border-violet-200 bg-violet-50 text-violet-800"
              >
                Mark signed
              </button>
            )}
            {active.status === "sent" && active.document_type === "invoice" && (
              <button
                type="button"
                disabled={updateMutation.isPending}
                onClick={() => markStatus("paid")}
                className="text-[10px] px-2 py-0.5 rounded border border-emerald-200 bg-emerald-50 text-emerald-800"
              >
                Mark paid
              </button>
            )}
          </div>
          <p className="text-[9px] text-amber-700 font-medium">
            Draft only. Review before signing.
          </p>
        </div>
      )}
    </div>
  );
}

function ProposalsSection({ leadId, lead }: { leadId: string; lead: CrmLead }) {
  const queryClient = useQueryClient();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [editText, setEditText] = useState("");
  const [copied, setCopied] = useState(false);

  const { data: proposalsData, isLoading } = useQuery({
    queryKey: ["crm-proposals", leadId],
    queryFn: () => crmApi.listProposals(leadId).then((r) => r.data),
  });

  const { data: v2ProposalsData, isLoading: v2Loading } = useQuery({
    queryKey: ["proposals", "lead", leadId],
    queryFn: () => proposalsApi.list({ lead_id: leadId, limit: 20 }).then((r) => r.data),
  });

  const proposals = normalizeList<CrmProposal>(proposalsData);
  const active =
    proposals.find((p) => p.id === selectedId) ?? proposals[0] ?? null;

  const generateMutation = useMutation({
    mutationFn: () =>
      crmApi
        .generateProposal(leadId, { language: lead.language || "ru" })
        .then((r) => r.data),
    onSuccess: (p) => {
      setSelectedId(p.id);
      setEditing(false);
      queryClient.invalidateQueries({ queryKey: ["crm-proposals", leadId] });
      toast.success("Proposal generated — review before sending");
    },
    onError: (err: Error) => toast.error(err.message || "Generation failed"),
  });

  const updateMutation = useMutation({
    mutationFn: (data: Parameters<typeof crmApi.updateProposal>[1]) =>
      crmApi.updateProposal(active!.id, data).then((r) => r.data),
    onSuccess: (p) => {
      setSelectedId(p.id);
      setEditing(false);
      queryClient.invalidateQueries({ queryKey: ["crm-proposals", leadId] });
      toast.success("Proposal updated");
    },
    onError: (err: Error) => toast.error(err.message || "Update failed"),
  });

  const markStatus = (status: ProposalStatus) => {
    if (!active) return;
    updateMutation.mutate({ status });
  };

  const copyProposal = async () => {
    if (!active) return;
    await navigator.clipboard.writeText(active.proposal_text);
    setCopied(true);
    toast.success("Copied to clipboard");
    setTimeout(() => setCopied(false), 2000);
  };

  const startEdit = () => {
    if (!active) return;
    setEditText(active.proposal_text);
    setEditing(true);
  };

  const saveEdit = () => {
    if (!active || !editText.trim()) return;
    updateMutation.mutate({ proposal_text: editText.trim() });
  };

  return (
    <div className="rounded-xl border border-emerald-200 bg-emerald-50/50 p-3 space-y-3">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs font-semibold text-emerald-950 flex items-center gap-1.5">
          <FileText size={14} />
          Proposals
        </p>
        <div className="flex items-center gap-1.5">
          <Link
            href={`/proposals/new?client_id=${lead.client_id}&lead_id=${leadId}`}
            className="text-[10px] px-2 py-1 rounded border border-indigo-300 bg-indigo-50 text-indigo-900 hover:bg-indigo-100 flex items-center gap-1"
          >
            <FileText size={10} />
            Proposal v2
          </Link>
          <button
            type="button"
            disabled={generateMutation.isPending}
            onClick={() => generateMutation.mutate()}
            className="text-[10px] px-2 py-1 rounded border border-emerald-300 bg-white text-emerald-900 hover:bg-emerald-100 disabled:opacity-50 flex items-center gap-1"
          >
            {generateMutation.isPending ? (
              <Loader2 size={10} className="animate-spin" />
            ) : (
              <Sparkles size={10} />
            )}
            Generate proposal
          </button>
        </div>
      </div>

      {isLoading && <p className="text-[11px] text-gray-400">Loading…</p>}

      {!isLoading && proposals.length === 0 && (
        <p className="text-[11px] text-emerald-800/70">No proposals yet — generate a draft.</p>
      )}

      {proposals.length > 1 && (
        <select
          className="input w-full text-xs"
          value={active?.id ?? ""}
          onChange={(e) => {
            setSelectedId(e.target.value);
            setEditing(false);
          }}
        >
          {proposals.map((p) => (
            <option key={p.id} value={p.id}>
              {p.title} · {p.status} · {format(parseISO(p.created_at), "MMM d")}
            </option>
          ))}
        </select>
      )}

      {active && (
        <div className="rounded-lg border border-emerald-200 bg-white p-2.5 space-y-2">
          <div className="flex items-start justify-between gap-2">
            <p className="text-xs font-semibold text-gray-900 leading-snug">{active.title}</p>
            <span
              className={cn(
                "text-[9px] px-1.5 py-0.5 rounded-full border font-medium capitalize shrink-0",
                PROPOSAL_STATUS_STYLE[active.status],
              )}
            >
              {active.status}
            </span>
          </div>

          {active.valid_until && (
            <p className="text-[10px] text-gray-500">
              Valid until {format(parseISO(active.valid_until), "MMM d, yyyy")}
            </p>
          )}

          {editing ? (
            <textarea
              className="input w-full text-[11px] min-h-[200px] font-mono"
              value={editText}
              onChange={(e) => setEditText(e.target.value)}
            />
          ) : (
            <div className="rounded bg-gray-50 p-2 text-[11px] text-gray-800 max-h-48 overflow-y-auto whitespace-pre-wrap font-mono leading-relaxed">
              {active.proposal_text}
            </div>
          )}

          <div className="flex flex-wrap gap-1">
            {editing ? (
              <>
                <button
                  type="button"
                  disabled={updateMutation.isPending}
                  onClick={saveEdit}
                  className="text-[10px] px-2 py-0.5 rounded border border-emerald-300 bg-emerald-50 flex items-center gap-1"
                >
                  <Save size={10} /> Save
                </button>
                <button
                  type="button"
                  onClick={() => setEditing(false)}
                  className="text-[10px] px-2 py-0.5 rounded border border-gray-200"
                >
                  Cancel
                </button>
              </>
            ) : (
              <>
                <button
                  type="button"
                  onClick={copyProposal}
                  className="text-[10px] px-2 py-0.5 rounded border border-gray-200 flex items-center gap-1"
                >
                  {copied ? <Check size={10} /> : <Copy size={10} />}
                  Copy
                </button>
                <button
                  type="button"
                  onClick={startEdit}
                  className="text-[10px] px-2 py-0.5 rounded border border-gray-200 flex items-center gap-1"
                >
                  <Pencil size={10} /> Edit
                </button>
              </>
            )}
            {active.status === "draft" && (
              <button
                type="button"
                disabled={updateMutation.isPending}
                onClick={() => markStatus("sent")}
                className="text-[10px] px-2 py-0.5 rounded border border-sky-200 bg-sky-50 text-sky-800"
              >
                Mark sent
              </button>
            )}
            {(active.status === "draft" || active.status === "sent") && (
              <>
                <button
                  type="button"
                  disabled={updateMutation.isPending}
                  onClick={() => markStatus("accepted")}
                  className="text-[10px] px-2 py-0.5 rounded border border-emerald-200 bg-emerald-50 text-emerald-800"
                >
                  Mark accepted
                </button>
                <button
                  type="button"
                  disabled={updateMutation.isPending}
                  onClick={() => markStatus("rejected")}
                  className="text-[10px] px-2 py-0.5 rounded border border-red-200 bg-red-50 text-red-800"
                >
                  Mark rejected
                </button>
              </>
            )}
          </div>
          <p className="text-[9px] text-gray-400">Draft only — copy and send manually.</p>

          <DocumentsSection
            proposalId={active.id}
            proposalStatus={active.status}
            language={lead.language || active.language || "ru"}
          />
        </div>
      )}

      <div className="border-t border-emerald-200 pt-3 space-y-2">
        <p className="text-[10px] font-semibold text-indigo-900 uppercase tracking-wide">Proposal v2</p>
        {v2Loading && <p className="text-[11px] text-gray-400">Loading v2 proposals…</p>}
        {!v2Loading && normalizeList(v2ProposalsData).length === 0 && (
          <p className="text-[11px] text-gray-500">No v2 proposals linked to this lead.</p>
        )}
        <ul className="space-y-2">
          {normalizeList(v2ProposalsData).map((p) => (
            <li key={p.id} className="rounded-lg border border-indigo-100 bg-white p-2.5 text-[11px]">
              <div className="flex items-start justify-between gap-2">
                <Link href={`/proposals/${p.id}`} className="font-medium text-indigo-900 hover:underline leading-snug">
                  {p.title}
                </Link>
                <span
                  className={cn(
                    "text-[9px] px-1.5 py-0.5 rounded-full border font-medium capitalize shrink-0",
                    V2_PROPOSAL_STATUS_STYLE[p.status as ProposalDocumentStatus],
                  )}
                >
                  {p.status}
                </span>
              </div>
              <p className="text-[9px] text-gray-400 mt-1">
                {format(parseISO(p.created_at), "MMM d, yyyy")}
                {p.sent_at && ` · Sent ${format(parseISO(p.sent_at), "MMM d")}`}
                {p.accepted_at && ` · Accepted ${format(parseISO(p.accepted_at), "MMM d")}`}
                {p.rejected_at && ` · Rejected ${format(parseISO(p.rejected_at), "MMM d")}`}
              </p>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

function OutreachSection({ leadId, lead }: { leadId: string; lead: CrmLead }) {
  const { data, isLoading } = useQuery({
    queryKey: ["outreach", "lead", leadId],
    queryFn: () => outreachApi.list({ lead_id: leadId, limit: 20 }).then((r) => r.data),
  });

  const items = normalizeList(data);

  return (
    <div className="rounded-xl border border-indigo-200 bg-indigo-50/40 p-3 space-y-3">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs font-semibold text-indigo-950 flex items-center gap-1.5">
          <Send size={14} />
          Outreach
        </p>
        <Link
          href={`/outreach/new?lead_id=${leadId}&buyer_name=${encodeURIComponent(lead.name)}&buyer_company=${encodeURIComponent(lead.company ?? "")}&country=Uzbekistan&outreach_type=first_contact`}
          className="text-[10px] px-2 py-1 rounded border border-indigo-300 bg-white text-indigo-900 hover:bg-indigo-100 flex items-center gap-1"
        >
          <Send size={10} />
          New outreach
        </Link>
      </div>

      {isLoading && <p className="text-[11px] text-gray-400">Loading…</p>}

      {!isLoading && items.length === 0 && (
        <p className="text-[11px] text-indigo-800/70">No outreach drafts linked to this lead.</p>
      )}

      {items.length > 0 && (
        <ul className="space-y-2">
          {items.map((o) => (
            <li key={o.id} className="rounded-lg border border-indigo-100 bg-white p-2.5 text-[11px]">
              <div className="flex items-start justify-between gap-2">
                <Link href={`/outreach/${o.id}`} className="font-medium text-indigo-900 hover:underline leading-snug">
                  {o.buyer_company || o.buyer_name || o.channel}
                </Link>
                <span
                  className={cn(
                    "text-[9px] px-1.5 py-0.5 rounded-full border font-medium capitalize shrink-0",
                    OUTREACH_STATUS_STYLE[o.status as OutreachStatus],
                  )}
                >
                  {o.status}
                </span>
              </div>
              <p className="text-[9px] text-gray-400 mt-1">
                {o.channel} · {o.outreach_type.replace(/_/g, " ")}
                {o.approved_at && ` · Approved ${format(parseISO(o.approved_at), "MMM d")}`}
                {o.sent_at && ` · Sent ${format(parseISO(o.sent_at), "MMM d")}`}
              </p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function PlaybookSection({ leadId, lead }: { leadId: string; lead: CrmLead }) {
  const queryClient = useQueryClient();
  const [recommended, setRecommended] = useState<SalesPlaybook[]>([]);
  const [matchReasons, setMatchReasons] = useState<Record<string, string[]>>({});
  const [selectedId, setSelectedId] = useState("");
  const [productId, setProductId] = useState("");

  const { data: products } = useQuery({
    queryKey: ["products", "client", lead.client_id],
    queryFn: () => productsApi.list({ client_id: lead.client_id, limit: 50 }).then((r) => r.data),
    enabled: !!lead.client_id,
  });

  const recommendMutation = useMutation({
    mutationFn: () =>
      salesPlaybooksApi
        .recommend({ lead_id: leadId, client_id: lead.client_id })
        .then((r) => r.data),
    onSuccess: (data) => {
      setRecommended(data.items);
      setMatchReasons(data.match_reasons ?? {});
      if (data.items[0]) setSelectedId(data.items[0].id);
      toast.success(data.items.length ? `Found ${data.items.length} playbook(s)` : "No matching playbooks");
    },
    onError: (err: Error) => toast.error(err.message || "Recommend failed"),
  });

  const applyMutation = useMutation({
    mutationFn: () =>
      salesPlaybooksApi
        .applyToLead(selectedId, leadId, { product_id: productId || null })
        .then((r) => r.data),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["outreach", "lead", leadId] });
      queryClient.invalidateQueries({ queryKey: ["crm-activities", leadId] });
      toast.success(data.message || "Playbook applied");
    },
    onError: (err: Error) => toast.error(err.message || "Apply failed"),
  });

  return (
    <div className="rounded-xl border border-violet-200 bg-violet-50/40 p-3 space-y-3">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs font-semibold text-violet-950 flex items-center gap-1.5">
          <ClipboardList size={14} />
          Sales Playbooks
        </p>
        <Link
          href="/sales-playbooks"
          className="text-[10px] px-2 py-1 rounded border border-violet-300 bg-white text-violet-900 hover:bg-violet-100"
        >
          View all
        </Link>
      </div>

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          disabled={recommendMutation.isPending}
          onClick={() => recommendMutation.mutate()}
          className="text-[10px] px-2 py-1 rounded border border-violet-300 bg-white text-violet-900 hover:bg-violet-100 disabled:opacity-50 flex items-center gap-1"
        >
          {recommendMutation.isPending ? <Loader2 size={10} className="animate-spin" /> : <Sparkles size={10} />}
          Recommend playbook
        </button>
      </div>

      {recommended.length > 0 && (
        <div className="space-y-2">
          <select
            className="input w-full text-xs"
            value={selectedId}
            onChange={(e) => setSelectedId(e.target.value)}
          >
            {recommended.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name} ({p.status})
              </option>
            ))}
          </select>
          {selectedId && matchReasons[selectedId]?.length > 0 && (
            <p className="text-[9px] text-violet-700">
              Match: {matchReasons[selectedId].join(", ")}
            </p>
          )}
          {normalizeList(products).length > 0 && (
            <select
              className="input w-full text-xs"
              value={productId}
              onChange={(e) => setProductId(e.target.value)}
            >
              <option value="">Product (optional)</option>
              {normalizeList(products).map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
          )}
          <button
            type="button"
            disabled={!selectedId || applyMutation.isPending}
            onClick={() => applyMutation.mutate()}
            className="text-[10px] px-2 py-1 rounded bg-violet-700 text-white hover:bg-violet-800 disabled:opacity-50 w-full"
          >
            {applyMutation.isPending ? "Applying…" : "Apply playbook (drafts only)"}
          </button>
          <p className="text-[9px] text-amber-700">
            Creates draft outreach, proposals, and tasks — nothing is sent automatically.
          </p>
        </div>
      )}

      {recommended.length === 0 && !recommendMutation.isPending && (
        <p className="text-[11px] text-violet-800/70">
          Recommend a playbook for this lead, or create one in Sales Playbooks.
        </p>
      )}
    </div>
  );
}

function LeadIntelligencePanel({ leadId, lead }: { leadId: string; lead: CrmLead }) {
  const queryClient = useQueryClient();
  const [insights, setInsights] = useState<LeadInsights | null>(lead.lead_insights ?? null);

  const scoreMutation = useMutation({
    mutationFn: () => crmApi.scoreLead(leadId).then((r) => r.data),
    onSuccess: (data) => {
      setInsights(data.insights);
      queryClient.invalidateQueries({ queryKey: ["crm-pipeline"] });
      queryClient.invalidateQueries({ queryKey: ["crm-lead", leadId] });
      toast.success(data.demo_mode ? "Lead scored (demo mode)" : "Lead intelligence updated");
    },
    onError: (err: Error) => toast.error(err.message || "Scoring failed"),
  });

  const display = insights ?? (lead.lead_score != null && lead.qualification_level
    ? {
        score: lead.lead_score,
        level: lead.qualification_level,
        strengths: [] as string[],
        risks: [] as string[],
        next_action: lead.recommended_action || "",
      }
    : null);

  return (
    <div className="rounded-xl border border-orange-200 bg-orange-50/40 p-3 space-y-3">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs font-semibold text-orange-950 flex items-center gap-1.5">
          <Sparkles size={14} />
          AI Lead Intelligence
        </p>
        <button
          type="button"
          disabled={scoreMutation.isPending}
          onClick={() => scoreMutation.mutate()}
          className="text-[10px] px-2 py-1 rounded border border-orange-300 bg-white text-orange-900 hover:bg-orange-100 disabled:opacity-50 flex items-center gap-1"
        >
          {scoreMutation.isPending ? <Loader2 size={10} className="animate-spin" /> : <Sparkles size={10} />}
          {display ? "Re-score" : "Score lead"}
        </button>
      </div>

      {!display && (
        <p className="text-[11px] text-orange-800/70">
          Run AI scoring to prioritize this lead — no status or outreach changes.
        </p>
      )}

      {display && (
        <div className="space-y-2 text-[11px]">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-lg font-bold text-orange-950 tabular-nums">
              {scoreBadgeLabel(display.score, display.level)}
            </span>
            <span className="px-2 py-0.5 rounded-full bg-white border border-orange-200 capitalize text-orange-900">
              {display.level}
            </span>
            {lead.last_scored_at && (
              <span className="text-[9px] text-gray-400">
                {format(parseISO(lead.last_scored_at), "MMM d, HH:mm")}
              </span>
            )}
          </div>
          {lead.ai_summary && (
            <p className="text-gray-700">{lead.ai_summary}</p>
          )}
          {display.strengths.length > 0 && (
            <div>
              <p className="font-semibold text-emerald-800">Strengths</p>
              <ul className="list-disc pl-4 text-gray-600">
                {(display.strengths.length ? display.strengths : []).map((s) => (
                  <li key={s}>{s}</li>
                ))}
              </ul>
            </div>
          )}
          {display.risks.length > 0 && (
            <div>
              <p className="font-semibold text-red-800">Risks</p>
              <ul className="list-disc pl-4 text-gray-600">
                {display.risks.map((r) => (
                  <li key={r}>{r}</li>
                ))}
              </ul>
            </div>
          )}
          {(display.next_action || lead.recommended_action) && (
            <div className="rounded border border-orange-100 bg-white p-2">
              <p className="font-semibold text-gray-800">Recommendation</p>
              <p className="text-gray-700 mt-0.5">{display.next_action || lead.recommended_action}</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function SalesCopilotPanel({
  lead,
  leadId,
  onLeadUpdated,
}: {
  lead: CrmLead;
  leadId: string;
  onLeadUpdated: () => void;
}) {
  const queryClient = useQueryClient();
  const [suggestion, setSuggestion] = useState<CrmAiSuggestNextStep | null>(null);
  const [generated, setGenerated] = useState<CrmAiGeneratedMessage | null>(null);
  const [copied, setCopied] = useState(false);
  const lang = lead.language || "ru";

  const suggestMutation = useMutation({
    mutationFn: () => crmApi.suggestNextStep(leadId).then((r) => r.data),
    onSuccess: (data) => {
      setSuggestion(data);
      setGenerated(null);
      queryClient.invalidateQueries({ queryKey: ["crm-activities", leadId] });
      toast.success("Next step suggested — saved to activities");
    },
    onError: (err: Error) => toast.error(err.message || "Suggestion failed"),
  });

  const generateMutation = useMutation({
    mutationFn: (purpose: MessagePurpose) =>
      crmApi.generateMessage(leadId, { purpose, language: lang }).then((r) => r.data),
    onSuccess: (data) => {
      setGenerated(data);
      toast.success("Message generated — review before sending");
    },
    onError: (err: Error) => toast.error(err.message || "Generation failed"),
  });

  const saveMutation = useMutation({
    mutationFn: (data: CrmAiGeneratedMessage) =>
      crmApi
        .saveMessageActivity(leadId, {
          message_text: data.message_text,
          purpose: data.purpose,
          tone: data.tone,
        })
        .then((r) => r.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["crm-activities", leadId] });
      toast.success("Saved as activity");
    },
    onError: (err: Error) => toast.error(err.message || "Save failed"),
  });

  const applyStatusMutation = useMutation({
    mutationFn: (status: LeadStatus) =>
      crmApi.updateLead(leadId, { status }).then((r) => r.data),
    onSuccess: () => {
      onLeadUpdated();
      toast.success("Status updated");
    },
    onError: (err: Error) => toast.error(err.message || "Status update failed"),
  });

  const applyFollowUpMutation = useMutation({
    mutationFn: (iso: string) =>
      crmApi.updateLead(leadId, { next_follow_up_at: iso }).then((r) => r.data),
    onSuccess: () => {
      onLeadUpdated();
      toast.success("Follow-up date applied");
    },
    onError: (err: Error) => toast.error(err.message || "Update failed"),
  });

  const copyText = async (text: string) => {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    toast.success("Copied to clipboard");
    setTimeout(() => setCopied(false), 2000);
  };

  const busy = suggestMutation.isPending || generateMutation.isPending;

  return (
    <div className="rounded-xl border border-blue-200 bg-blue-50/60 p-3 space-y-3">
      <p className="text-xs font-semibold text-blue-950 flex items-center gap-1.5">
        <Bot size={14} />
        AI Sales Copilot
      </p>
      <p className="text-[10px] text-blue-800/80">
        Suggestions only — you send messages and change status manually.
      </p>

      <div className="flex flex-wrap gap-1">
        <button
          type="button"
          disabled={busy}
          onClick={() => suggestMutation.mutate()}
          className="text-[10px] px-2 py-1 rounded border border-blue-300 bg-white text-blue-900 hover:bg-blue-100 disabled:opacity-50 flex items-center gap-1"
        >
          {suggestMutation.isPending ? (
            <Loader2 size={10} className="animate-spin" />
          ) : (
            <Sparkles size={10} />
          )}
          Suggest next step
        </button>
        {(
          [
            ["first_contact", "First contact"],
            ["follow_up", "Follow-up"],
            ["proposal", "Proposal"],
            ["objection_reply", "Objection reply"],
          ] as const
        ).map(([purpose, label]) => (
          <button
            key={purpose}
            type="button"
            disabled={busy}
            onClick={() => generateMutation.mutate(purpose)}
            className="text-[10px] px-2 py-1 rounded border border-blue-200 bg-blue-50 text-blue-800 hover:bg-blue-100 disabled:opacity-50"
          >
            {generateMutation.isPending && generateMutation.variables === purpose ? "…" : label}
          </button>
        ))}
      </div>

      {suggestion && (
        <div className="rounded-lg border border-blue-200 bg-white p-2.5 text-[11px] space-y-2">
          <p className="font-medium text-blue-950">{suggestion.recommended_next_step}</p>
          <p className="text-gray-600 italic">{suggestion.reasoning}</p>
          <div className="rounded bg-gray-50 p-2 text-gray-800 whitespace-pre-wrap">
            {suggestion.suggested_message}
          </div>
          <div className="flex flex-wrap gap-1">
            <button
              type="button"
              onClick={() => copyText(suggestion.suggested_message)}
              className="text-[10px] px-2 py-0.5 rounded border border-gray-200 flex items-center gap-1"
            >
              {copied ? <Check size={10} /> : <Copy size={10} />}
              Copy message
            </button>
            {suggestion.suggested_status_change &&
              suggestion.suggested_status_change !== lead.status && (
                <button
                  type="button"
                  disabled={applyStatusMutation.isPending}
                  onClick={() => applyStatusMutation.mutate(suggestion.suggested_status_change!)}
                  className="text-[10px] px-2 py-0.5 rounded border border-indigo-200 bg-indigo-50 text-indigo-800"
                >
                  Apply status → {suggestion.suggested_status_change.replace("_", " ")}
                </button>
              )}
            {suggestion.follow_up_date && (
              <button
                type="button"
                disabled={applyFollowUpMutation.isPending}
                onClick={() => applyFollowUpMutation.mutate(suggestion.follow_up_date!)}
                className="text-[10px] px-2 py-0.5 rounded border border-orange-200 bg-orange-50 text-orange-800"
              >
                Apply follow-up date
              </button>
            )}
          </div>
        </div>
      )}

      {generated && (
        <div className="rounded-lg border border-violet-200 bg-white p-2.5 text-[11px] space-y-2">
          <p className="font-medium text-violet-950 capitalize">
            {generated.purpose.replace("_", " ")} · {generated.tone}
          </p>
          <div className="rounded bg-gray-50 p-2 text-gray-800 whitespace-pre-wrap">
            {generated.message_text}
          </div>
          {generated.cta && (
            <p className="text-[10px] text-gray-500">CTA: {generated.cta}</p>
          )}
          <div className="flex flex-wrap gap-1">
            <button
              type="button"
              onClick={() => copyText(generated.message_text)}
              className="text-[10px] px-2 py-0.5 rounded border border-gray-200 flex items-center gap-1"
            >
              {copied ? <Check size={10} /> : <Copy size={10} />}
              Copy
            </button>
            <button
              type="button"
              disabled={saveMutation.isPending}
              onClick={() => saveMutation.mutate(generated)}
              className="text-[10px] px-2 py-0.5 rounded border border-violet-200 bg-violet-50 text-violet-800"
            >
              Save as activity
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function LeadDrawer({
  leadId,
  onClose,
}: {
  leadId: string;
  onClose: () => void;
}) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [activityType, setActivityType] = useState<CrmActivityType>("note");
  const [activityContent, setActivityContent] = useState("");

  const { data: lead, isLoading } = useQuery({
    queryKey: ["crm-lead", leadId],
    queryFn: () => crmApi.getLead(leadId).then((r) => r.data),
  });

  const { data: activitiesData } = useQuery({
    queryKey: ["crm-activities", leadId],
    queryFn: () => crmApi.listActivities(leadId).then((r) => r.data),
  });

  const { data: dealRoom } = useQuery({
    queryKey: ["crm-deal-lead", leadId],
    queryFn: () => crmApi.getDealForLead(leadId).then((r) => r.data),
  });

  const openDealRoomMutation = useMutation({
    mutationFn: () =>
      dealRoomApi
        .findOrCreate({
          crm_client_id: lead!.client_id,
          crm_lead_id: leadId,
          deal_name: lead!.name,
        })
        .then((r) => r.data),
    onSuccess: (room) => {
      router.push(`/deal-room?id=${room.id}`);
    },
    onError: (err: Error) => toast.error(err.message || "Failed to open deal room"),
  });

  const { data: attributionLinks } = useQuery({
    queryKey: ["attribution-links-crm", lead?.client_id],
    queryFn: () =>
      attributionLinksApi.list({ client_id: lead!.client_id, limit: 100 }).then((r) => r.data),
    enabled: !!lead?.client_id,
  });

  const updateMutation = useMutation({
    mutationFn: (data: Parameters<typeof crmApi.updateLead>[1]) =>
      crmApi.updateLead(leadId, data).then((r) => r.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["crm-pipeline"] });
      queryClient.invalidateQueries({ queryKey: ["crm-lead", leadId] });
      toast.success("Lead updated");
    },
    onError: (err: Error) => toast.error(err.message || "Update failed"),
  });

  const activityMutation = useMutation({
    mutationFn: () =>
      crmApi.addActivity(leadId, { type: activityType, content: activityContent }).then((r) => r.data),
    onSuccess: () => {
      setActivityContent("");
      queryClient.invalidateQueries({ queryKey: ["crm-activities", leadId] });
      queryClient.invalidateQueries({ queryKey: ["crm-pipeline"] });
      toast.success("Activity added");
    },
    onError: (err: Error) => toast.error(err.message || "Failed to add activity"),
  });

  if (isLoading || !lead) {
    return (
      <div className="fixed inset-y-0 right-0 w-full max-w-md bg-white border-l border-gray-200 shadow-xl z-40 p-6">
        <p className="text-sm text-gray-400">Loading lead…</p>
      </div>
    );
  }

  const followUpLocal = lead.next_follow_up_at
    ? format(parseISO(lead.next_follow_up_at), "yyyy-MM-dd'T'HH:mm")
    : "";

  return (
    <div className="fixed inset-y-0 right-0 w-full max-w-md bg-white border-l border-gray-200 shadow-xl z-40 flex flex-col">
      <div className="flex items-start justify-between p-4 border-b border-gray-100">
        <div>
          <h2 className="text-lg font-semibold text-gray-900">{lead.name}</h2>
          {lead.company && <p className="text-sm text-gray-500">{lead.company}</p>}
          {lead.company_name && (
            <p className="text-xs text-gray-400 mt-0.5">Client: {lead.company_name}</p>
          )}
        </div>
        <button type="button" onClick={onClose} className="p-1 rounded hover:bg-gray-100">
          <X size={18} />
        </button>
      </div>

      <div className="px-4 py-2 border-b border-gray-100 bg-violet-50/50 flex flex-wrap gap-3">
        <button
          type="button"
          disabled={openDealRoomMutation.isPending}
          onClick={() => openDealRoomMutation.mutate()}
          className="text-xs font-medium text-violet-800 hover:text-violet-950 flex items-center gap-1.5 disabled:opacity-50"
        >
          {openDealRoomMutation.isPending ? (
            <Loader2 size={14} className="animate-spin" />
          ) : (
            <Briefcase size={14} />
          )}
          Open Deal Room
        </button>
        <Link
          href={`/outreach/new?lead_id=${leadId}&buyer_name=${encodeURIComponent(lead.name)}&buyer_company=${encodeURIComponent(lead.company ?? "")}&country=Uzbekistan&outreach_type=first_contact`}
          className="text-xs font-medium text-indigo-800 hover:text-indigo-950 flex items-center gap-1.5"
        >
          <Send size={14} />
          Generate Outreach
        </Link>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        <div className="grid grid-cols-2 gap-2 text-xs">
          <label className="space-y-1">
            <span className="text-gray-500">Status</span>
            <select
              className="input w-full text-xs"
              value={lead.status}
              onChange={(e) =>
                updateMutation.mutate({ status: e.target.value as LeadStatus })
              }
            >
              {PIPELINE_COLUMNS.map((c) => (
                <option key={c.status} value={c.status}>
                  {c.label}
                </option>
              ))}
            </select>
          </label>
          <label className="space-y-1">
            <span className="text-gray-500">Priority</span>
            <select
              className="input w-full text-xs"
              value={lead.priority}
              onChange={(e) =>
                updateMutation.mutate({ priority: e.target.value as LeadPriority })
              }
            >
              <option value="high">High</option>
              <option value="medium">Medium</option>
              <option value="low">Low</option>
            </select>
          </label>
        </div>

        <div className="space-y-2 text-xs">
          {lead.phone && (
            <p className="flex items-center gap-2 text-gray-700">
              <Phone size={12} className="text-gray-400" /> {lead.phone}
            </p>
          )}
          {lead.email && (
            <p className="flex items-center gap-2 text-gray-700">
              <Mail size={12} className="text-gray-400" /> {lead.email}
            </p>
          )}
          {lead.telegram && (
            <p className="flex items-center gap-2 text-gray-700">
              <MessageCircle size={12} className="text-gray-400" /> {lead.telegram}
            </p>
          )}
          {lead.language && (
            <p className="text-gray-500">Language: {lead.language}</p>
          )}
        </div>

        <label className="block space-y-1 text-xs">
          <span className="text-gray-500">Attribution link</span>
          <select
            className="input w-full text-xs"
            value={lead.attribution_link_id ?? ""}
            onChange={(e) =>
              updateMutation.mutate({
                attribution_link_id: e.target.value || null,
              })
            }
          >
            <option value="">None</option>
            {normalizeList(attributionLinks).map((link) => (
              <option key={link.id} value={link.id}>
                {link.title} ({link.channel})
              </option>
            ))}
          </select>
          {lead.attribution_campaign && (
            <p className="text-[10px] text-gray-400 mt-0.5">
              Campaign: {lead.attribution_campaign}
              {lead.attribution_source ? ` · ${lead.attribution_source}` : ""}
            </p>
          )}
          {lead.revenue_attribution && (
            <div className="mt-2 rounded-lg border border-emerald-100 bg-emerald-50/40 px-2 py-1.5 text-[10px] text-emerald-900">
              <p className="font-medium">Revenue attribution</p>
              <p>
                Source: {lead.revenue_attribution.source_label} · Channel:{" "}
                {lead.revenue_attribution.channel_label}
              </p>
              {lead.revenue_attribution.deal_count > 0 && (
                <p>Won revenue: {lead.revenue_attribution.won_revenue}</p>
              )}
              <Link href="/revenue-attribution" className="text-brand-700 hover:underline">
                Open attribution dashboard →
              </Link>
            </div>
          )}
        </label>

        {lead.interest && (
          <div>
            <p className="text-xs font-medium text-gray-700 mb-1">Interest</p>
            <p className="text-xs text-gray-600 whitespace-pre-wrap">{lead.interest}</p>
          </div>
        )}

        <label className="block space-y-1 text-xs">
          <span className="text-gray-500">Notes</span>
          <textarea
            className="input w-full text-xs min-h-[72px]"
            defaultValue={lead.notes ?? ""}
            onBlur={(e) => {
              if (e.target.value !== (lead.notes ?? "")) {
                updateMutation.mutate({ notes: e.target.value || null });
              }
            }}
          />
        </label>

        <div className="grid grid-cols-2 gap-2 text-xs">
          <label className="space-y-1">
            <span className="text-gray-500">Est. value</span>
            <input
              type="number"
              className="input w-full text-xs"
              defaultValue={lead.estimated_value ?? ""}
              onBlur={(e) => {
                const v = e.target.value ? parseFloat(e.target.value) : null;
                updateMutation.mutate({ estimated_value: v });
              }}
            />
          </label>
          <label className="space-y-1">
            <span className="text-gray-500">Next follow-up</span>
            <input
              type="datetime-local"
              className="input w-full text-xs"
              defaultValue={followUpLocal}
              onBlur={(e) => {
                const iso = e.target.value ? new Date(e.target.value).toISOString() : null;
                updateMutation.mutate({ next_follow_up_at: iso });
              }}
            />
          </label>
        </div>

        <LeadIntelligencePanel leadId={leadId} lead={lead} />

        <SalesCopilotPanel
          lead={lead}
          leadId={leadId}
          onLeadUpdated={() => {
            queryClient.invalidateQueries({ queryKey: ["crm-pipeline"] });
            queryClient.invalidateQueries({ queryKey: ["crm-lead", leadId] });
          }}
        />

        <ProductMatchPanel leadId={leadId} />

        <PartnerMatchPanel mode="lead" entityId={leadId} />

        <ProposalsSection leadId={leadId} lead={lead} />

        <OutreachSection leadId={leadId} lead={lead} />

        <PlaybookSection leadId={leadId} lead={lead} />

        <div className="border-t border-gray-100 pt-4">
          <p className="text-xs font-semibold text-gray-800 mb-2">Activities</p>
          <div className="space-y-2 mb-3 max-h-40 overflow-y-auto">
            {normalizeList<CrmActivity>(activitiesData).length === 0 ? (
              <p className="text-[11px] text-gray-400">No activities yet</p>
            ) : (
              normalizeList<CrmActivity>(activitiesData).map((a) => (
                <div key={a.id} className="rounded border border-gray-100 bg-gray-50 p-2 text-[11px]">
                  <p className="font-medium text-gray-700 capitalize">
                    {a.type.replace("_", " ")}{" "}
                    <span className="font-normal text-gray-400">
                      · {format(parseISO(a.created_at), "MMM d, HH:mm")}
                    </span>
                  </p>
                  <p className="text-gray-600 mt-0.5 whitespace-pre-wrap">{a.content}</p>
                </div>
              ))
            )}
          </div>
          <div className="flex gap-2">
            <select
              className="input text-xs w-28"
              value={activityType}
              onChange={(e) => setActivityType(e.target.value as CrmActivityType)}
            >
              {ACTIVITY_TYPES.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </select>
            <input
              className="input text-xs flex-1"
              placeholder="Add activity…"
              value={activityContent}
              onChange={(e) => setActivityContent(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && activityContent.trim()) {
                  activityMutation.mutate();
                }
              }}
            />
            <button
              type="button"
              className="btn-primary text-xs px-2"
              disabled={!activityContent.trim() || activityMutation.isPending}
              onClick={() => activityMutation.mutate()}
            >
              Add
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function ExtractLeadModal({
  clientId,
  clients,
  onClose,
  onCreated,
}: {
  clientId: string;
  clients: { id: string; company_name: string }[];
  onClose: () => void;
  onCreated: (leadId: string) => void;
}) {
  const [selectedClient, setSelectedClient] = useState(clientId);
  const [text, setText] = useState("");
  const [extracted, setExtracted] = useState<CrmExtractResult | null>(null);

  const extractMutation = useMutation({
    mutationFn: () =>
      crmApi.extractLead({ client_id: selectedClient, text }).then((r) => r.data),
    onSuccess: (data) => {
      setExtracted(data);
      toast.success("Lead extracted — review before saving");
    },
    onError: (err: Error) => toast.error(err.message || "Extraction failed"),
  });

  const createMutation = useMutation({
    mutationFn: () =>
      crmApi
        .createLead({
          client_id: selectedClient,
          name: extracted?.name || "Unknown contact",
          company: extracted?.company,
          phone: extracted?.phone,
          telegram: extracted?.telegram,
          email: extracted?.email,
          interest: extracted?.interest,
          language: extracted?.language,
          priority: extracted?.priority ?? "medium",
          notes: extracted?.suggested_next_step
            ? `Suggested next step: ${extracted.suggested_next_step}`
            : undefined,
          source: "telegram",
        })
        .then((r) => r.data),
    onSuccess: (lead) => {
      toast.success("Lead created");
      onCreated(lead.id);
      onClose();
    },
    onError: (err: Error) => toast.error(err.message || "Create failed"),
  });

  return (
    <div
      data-app-modal
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/30"
    >
      <div className="bg-white rounded-xl shadow-xl w-full max-w-lg max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between p-4 border-b border-gray-100">
          <h2 className="text-sm font-semibold text-gray-900 flex items-center gap-2">
            <Sparkles size={16} className="text-violet-600" />
            Extract lead from text
          </h2>
          <button type="button" onClick={onClose} className="p-1 rounded hover:bg-gray-100">
            <X size={18} />
          </button>
        </div>
        <div className="p-4 space-y-3">
          <label className="block text-xs">
            <span className="text-gray-500 font-medium">Client</span>
            <select
              className="input w-full mt-1 text-sm"
              value={selectedClient}
              onChange={(e) => {
                setSelectedClient(e.target.value);
                setExtracted(null);
              }}
            >
              <option value="">Select client…</option>
              {clients.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.company_name}
                </option>
              ))}
            </select>
          </label>
          <label className="block text-xs">
            <span className="text-gray-500 font-medium">Message / inquiry text</span>
            <textarea
              className="input w-full mt-1 text-sm min-h-[120px]"
              placeholder="Paste Telegram message, email, or inquiry…"
              value={text}
              onChange={(e) => {
                setText(e.target.value);
                setExtracted(null);
              }}
            />
          </label>
          <button
            type="button"
            className="btn-secondary text-sm w-full flex items-center justify-center gap-1"
            disabled={!selectedClient || !text.trim() || extractMutation.isPending}
            onClick={() => extractMutation.mutate()}
          >
            {extractMutation.isPending ? (
              <Loader2 size={14} className="animate-spin" />
            ) : (
              <Sparkles size={14} />
            )}
            Extract lead
          </button>

          {extracted && (
            <div className="rounded-lg border border-violet-200 bg-violet-50 p-3 text-xs space-y-1.5">
              <p className="font-medium text-violet-950">Extracted ({extracted.source})</p>
              {extracted.name && <p><span className="text-violet-700">Name:</span> {extracted.name}</p>}
              {extracted.company && <p><span className="text-violet-700">Company:</span> {extracted.company}</p>}
              {extracted.phone && <p><span className="text-violet-700">Phone:</span> {extracted.phone}</p>}
              {extracted.telegram && <p><span className="text-violet-700">Telegram:</span> {extracted.telegram}</p>}
              {extracted.email && <p><span className="text-violet-700">Email:</span> {extracted.email}</p>}
              {extracted.interest && <p><span className="text-violet-700">Interest:</span> {extracted.interest}</p>}
              {extracted.suggested_next_step && (
                <p className="text-violet-800 italic mt-1">{extracted.suggested_next_step}</p>
              )}
              <button
                type="button"
                className="btn-primary text-xs w-full mt-2"
                disabled={createMutation.isPending}
                onClick={() => createMutation.mutate()}
              >
                {createMutation.isPending ? "Creating…" : "Create lead"}
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default function CrmPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const searchParams = useSearchParams();
  const [clientId, setClientId] = useState("");
  const [selectedLeadId, setSelectedLeadId] = useState<string | null>(null);
  const [showExtract, setShowExtract] = useState(false);

  useEffect(() => {
    const lead = searchParams.get("lead");
    if (lead) setSelectedLeadId(lead);
  }, [searchParams]);

  const { data: clients } = useQuery({
    queryKey: ["clients"],
    queryFn: () => clientsApi.list().then((r) => r.data),
  });
  const clientOptions = normalizeList<Client>(clients);

  const { data: pipeline, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["crm-pipeline", clientId],
    queryFn: () =>
      crmApi.pipeline(clientId ? { client_id: clientId } : undefined).then((r) => r.data),
  });

  const { data: classificationData } = useQuery({
    queryKey: ["lead-intelligence-leads-crm", clientId],
    queryFn: () =>
      leadIntelligenceApi
        .leads({ client_id: clientId || undefined, limit: 500 })
        .then((r) => r.data),
    staleTime: 60_000,
  });

  const { data: buyerIntelData } = useQuery({
    queryKey: ["buyer-intelligence-crm", clientId],
    queryFn: () =>
      buyerIntelligenceApi
        .buyers({ client_id: clientId || undefined, limit: 500 })
        .then((r) => r.data),
    staleTime: 60_000,
  });

  const classificationMap = useMemo(() => {
    const map = new Map<string, { classification: LeadClassification; score: number }>();
    for (const item of classificationData?.items ?? []) {
      map.set(item.lead_id, { classification: item.classification, score: item.score });
    }
    return map;
  }, [classificationData?.items]);

  const buyerIntelMap = useMemo(() => {
    const map = new Map<string, { classification: BuyerClassification; score: number }>();
    for (const item of buyerIntelData?.items ?? []) {
      map.set(item.buyer_id, { classification: item.classification, score: item.buyer_score });
    }
    return map;
  }, [buyerIntelData?.items]);

  const byStatus = useMemo(() => {
    const map: Record<LeadStatus, CrmLead[]> = {
      new: [],
      contacted: [],
      qualified: [],
      proposal_sent: [],
      negotiation: [],
      won: [],
      lost: [],
    };
    for (const col of pipeline?.columns ?? []) {
      if (col.status in map) {
        map[col.status] = col.leads;
      }
    }
    return map;
  }, [pipeline?.columns]);

  const createMutation = useMutation({
    mutationFn: () =>
      crmApi
        .createLead({
          client_id: clientId,
          name: "New lead",
          status: "new",
          priority: "medium",
        })
        .then((r) => r.data),
    onSuccess: (lead) => {
      queryClient.invalidateQueries({ queryKey: ["crm-pipeline"] });
      setSelectedLeadId(lead.id);
      toast.success("Lead created — edit details in drawer");
    },
    onError: (err: Error) => toast.error(err.message || "Failed to create lead"),
  });

  return (
    <div className="p-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-6">
        <div>
          <h1 className="text-xl font-semibold text-gray-900 flex items-center gap-2">
            <Users size={20} className="text-blue-600" />
            {t("crm.title")}
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            {t("crm.subtitle", { count: pipeline?.total ?? 0 })}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Link
            href="/crm/deals"
            className="btn-secondary text-sm flex items-center gap-1.5"
          >
            <Briefcase size={14} />
            {t("crm.deals")}
          </Link>
          <select
            className="input text-sm w-44"
            value={clientId}
            onChange={(e) => setClientId(e.target.value)}
          >
            <option value="">{t("common.allClients")}</option>
            {clientOptions.map((c) => (
              <option key={c.id} value={c.id}>
                {c.company_name}
              </option>
            ))}
          </select>
          <button
            type="button"
            className="btn-secondary text-sm flex items-center gap-1"
            onClick={() => setShowExtract(true)}
          >
            <Sparkles size={14} /> Extract lead
          </button>
          <button
            type="button"
            className="btn-primary text-sm flex items-center gap-1"
            disabled={!clientId || createMutation.isPending}
            onClick={() => createMutation.mutate()}
          >
            <Plus size={14} /> New lead
          </button>
        </div>
      </div>

      <PartialErrorsBanner errors={pipeline?.errors} />

      {isLoading ? (
        <LoadingState message="Loading pipeline…" />
      ) : isError ? (
        <ErrorState
          error={error}
          onRetry={() => refetch()}
        />
      ) : (
        <div className="overflow-x-auto pb-4">
          <div className="flex gap-3 min-w-max">
            {PIPELINE_COLUMNS.map(({ status, label, color }) => (
              <div
                key={status}
                className={cn("rounded-xl border p-3 w-52 shrink-0 min-h-[300px]", color)}
              >
                <div className="flex items-center justify-between mb-3">
                  <h2 className="text-xs font-semibold text-gray-800">{label}</h2>
                  <span className="text-[10px] text-gray-500 tabular-nums">
                    {byStatus[status].length}
                  </span>
                </div>
                <div className="space-y-2">
                  {byStatus[status].length === 0 ? (
                    <p className="text-[10px] text-gray-400 text-center py-4">Empty</p>
                  ) : (
                    byStatus[status].map((lead) => (
                      <LeadCard
                        key={lead.id}
                        lead={lead}
                        classification={classificationMap.get(lead.id)?.classification}
                        classificationScore={classificationMap.get(lead.id)?.score}
                        buyerClassification={buyerIntelMap.get(lead.id)?.classification}
                        buyerScore={buyerIntelMap.get(lead.id)?.score}
                        onClick={() => setSelectedLeadId(lead.id)}
                      />
                    ))
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {selectedLeadId && (
        <>
          <div
            data-app-modal
            className="fixed inset-0 bg-black/20 z-30"
            onClick={() => setSelectedLeadId(null)}
          />
          <LeadDrawer leadId={selectedLeadId} onClose={() => setSelectedLeadId(null)} />
        </>
      )}

      {showExtract && (
        <ExtractLeadModal
          clientId={clientId}
          clients={clientOptions}
          onClose={() => setShowExtract(false)}
          onCreated={(id) => {
            queryClient.invalidateQueries({ queryKey: ["crm-pipeline"] });
            setSelectedLeadId(id);
          }}
        />
      )}
    </div>
  );
}
