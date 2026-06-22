"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileText, Loader2, Plus, Trash2, X } from "lucide-react";
import toast from "react-hot-toast";
import {
  MESSAGE_TEMPLATE_CATEGORIES,
  communicationHubApi,
  type MessageTemplate,
  type MessageTemplateCategory,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/PageStates";
import { PageHeader, PageSection, PageShell } from "@/components/ui/design-system";
import { useTranslation } from "@/lib/I18nProvider";

type TemplateForm = {
  name: string;
  category: MessageTemplateCategory;
  content: string;
  language: string;
};

const EMPTY_FORM: TemplateForm = {
  name: "",
  category: "first_contact",
  content: "",
  language: "en",
};

function categoryLabel(cat: MessageTemplateCategory, t: (k: string) => string) {
  const key = `communicationsHub.templateCategory.${cat}`;
  const translated = t(key);
  return translated === key ? cat.replace(/_/g, " ") : translated;
}

export default function CommunicationsTemplatesPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [categoryFilter, setCategoryFilter] = useState<MessageTemplateCategory | "">("");
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<MessageTemplate | null>(null);
  const [form, setForm] = useState<TemplateForm>(EMPTY_FORM);

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["communication-templates", categoryFilter],
    queryFn: () =>
      communicationHubApi
        .listTemplates({ category: categoryFilter || undefined, limit: 100 })
        .then((r) => r.data),
  });

  const saveMut = useMutation({
    mutationFn: async () => {
      if (editing) {
        return communicationHubApi.updateTemplate(editing.id, form);
      }
      return communicationHubApi.createTemplate(form);
    },
    onSuccess: () => {
      toast.success(t(editing ? "communicationsHub.templateUpdated" : "communicationsHub.templateCreated"));
      setModalOpen(false);
      setEditing(null);
      setForm(EMPTY_FORM);
      qc.invalidateQueries({ queryKey: ["communication-templates"] });
    },
    onError: () => toast.error(t("communicationsHub.actionError")),
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => communicationHubApi.deleteTemplate(id),
    onSuccess: () => {
      toast.success(t("communicationsHub.templateDeleted"));
      qc.invalidateQueries({ queryKey: ["communication-templates"] });
    },
    onError: () => toast.error(t("communicationsHub.actionError")),
  });

  function openCreate() {
    setEditing(null);
    setForm(EMPTY_FORM);
    setModalOpen(true);
  }

  function openEdit(tpl: MessageTemplate) {
    setEditing(tpl);
    setForm({
      name: tpl.name,
      category: tpl.category,
      content: tpl.content,
      language: tpl.language,
    });
    setModalOpen(true);
  }

  return (
    <PageShell>
      <PageHeader
        title={t("communicationsHub.templatesTitle")}
        subtitle={t("communicationsHub.templatesSubtitle")}
        icon={FileText}
        actions={
          <button type="button" className="btn-primary text-sm flex items-center gap-1.5" onClick={openCreate}>
            <Plus size={14} />
            {t("communicationsHub.newTemplate")}
          </button>
        }
      />

      <div className="flex flex-wrap gap-2 mt-4">
        <button
          type="button"
          onClick={() => setCategoryFilter("")}
          className={cn(
            "text-sm px-3 py-1.5 rounded-lg border",
            !categoryFilter ? "bg-brand-50 border-brand-200 text-brand-800" : "border-gray-200 text-gray-600",
          )}
        >
          {t("common.all")}
        </button>
        {MESSAGE_TEMPLATE_CATEGORIES.map((cat) => (
          <button
            key={cat}
            type="button"
            onClick={() => setCategoryFilter(cat)}
            className={cn(
              "text-sm px-3 py-1.5 rounded-lg border capitalize",
              categoryFilter === cat
                ? "bg-brand-50 border-brand-200 text-brand-800"
                : "border-gray-200 text-gray-600",
            )}
          >
            {categoryLabel(cat, t)}
          </button>
        ))}
      </div>

      {isLoading ? (
        <LoadingState message={t("communicationsHub.loadingTemplates")} className="mt-4" />
      ) : isError ? (
        <ErrorState message={t("communicationsHub.loadError")} onRetry={() => refetch()} className="mt-4" />
      ) : !data || data.items.length === 0 ? (
        <EmptyState title={t("communicationsHub.emptyTemplates")} className="mt-4" />
      ) : (
        <PageSection title={t("communicationsHub.templatesList")} className="mt-4">
          <div className="grid md:grid-cols-2 gap-3">
            {data.items.map((tpl) => (
              <div key={tpl.id} className="card p-4 space-y-2">
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <p className="text-sm font-semibold text-gray-900">{tpl.name}</p>
                    <p className="text-xs text-gray-500 capitalize">
                      {categoryLabel(tpl.category, t)} · {tpl.language.toUpperCase()}
                    </p>
                  </div>
                  <div className="flex gap-1">
                    <button
                      type="button"
                      className="text-xs text-brand-600 hover:underline"
                      onClick={() => openEdit(tpl)}
                    >
                      {t("common.edit")}
                    </button>
                    <button
                      type="button"
                      className="text-xs text-red-600 hover:underline flex items-center gap-0.5"
                      onClick={() => {
                        if (confirm(t("communicationsHub.confirmDelete"))) {
                          deleteMut.mutate(tpl.id);
                        }
                      }}
                    >
                      <Trash2 size={12} />
                    </button>
                  </div>
                </div>
                <p className="text-xs text-gray-600 whitespace-pre-wrap line-clamp-4">{tpl.content}</p>
              </div>
            ))}
          </div>
        </PageSection>
      )}

      {modalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40">
          <div className="card w-full max-w-lg p-5 space-y-4 max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-semibold text-gray-900">
                {editing ? t("communicationsHub.editTemplate") : t("communicationsHub.newTemplate")}
              </h2>
              <button type="button" onClick={() => setModalOpen(false)} className="text-gray-400 hover:text-gray-600">
                <X size={18} />
              </button>
            </div>
            <input
              className="input w-full text-sm"
              placeholder={t("communicationsHub.templateName")}
              value={form.name}
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
            />
            <select
              className="input w-full text-sm"
              value={form.category}
              onChange={(e) =>
                setForm((f) => ({ ...f, category: e.target.value as MessageTemplateCategory }))
              }
            >
              {MESSAGE_TEMPLATE_CATEGORIES.map((cat) => (
                <option key={cat} value={cat}>
                  {categoryLabel(cat, t)}
                </option>
              ))}
            </select>
            <select
              className="input w-full text-sm"
              value={form.language}
              onChange={(e) => setForm((f) => ({ ...f, language: e.target.value }))}
            >
              <option value="en">EN</option>
              <option value="ru">RU</option>
              <option value="zh">ZH</option>
            </select>
            <textarea
              className="input w-full text-sm min-h-[140px]"
              placeholder={t("communicationsHub.templateContent")}
              value={form.content}
              onChange={(e) => setForm((f) => ({ ...f, content: e.target.value }))}
            />
            <div className="flex justify-end gap-2">
              <button type="button" className="btn-secondary text-sm" onClick={() => setModalOpen(false)}>
                {t("common.cancel")}
              </button>
              <button
                type="button"
                className="btn-primary text-sm flex items-center gap-1.5"
                disabled={!form.name.trim() || !form.content.trim() || saveMut.isPending}
                onClick={() => saveMut.mutate()}
              >
                {saveMut.isPending && <Loader2 size={14} className="animate-spin" />}
                {t("common.save")}
              </button>
            </div>
          </div>
        </div>
      )}
    </PageShell>
  );
}
