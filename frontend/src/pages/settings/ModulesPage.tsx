import { IconDatabase, IconFlame, IconServerCog, IconTerminal2, IconWifi, type Icon } from "@tabler/icons-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useAuth } from "../../auth/AuthProvider";
import { Card, ErrorNote, PageHeader, Toggle } from "../../components/ui";
import { t, type TextKey } from "../../i18n";
import { ApiError, request } from "../../lib/api";
import { MODULE_IDS, MODULES_KEY, useModules, type ModuleId, type Modules } from "../../lib/modules";

const META: Record<ModuleId, { icon: Icon; label: TextKey; desc: TextKey }> = {
  proxmox: { icon: IconServerCog, label: "mod.proxmox", desc: "mod.proxmox.desc" },
  unifi: { icon: IconWifi, label: "mod.unifi", desc: "mod.unifi.desc" },
  opnsense: { icon: IconFlame, label: "mod.opnsense", desc: "mod.opnsense.desc" },
  agents: { icon: IconTerminal2, label: "mod.agents", desc: "mod.agents.desc" },
  backups: { icon: IconDatabase, label: "mod.backups", desc: "mod.backups.desc" },
};

/** Lista modułów z przełącznikami (Ustawienia → Moduły i kreator pierwszej konfiguracji). */
export function ModuleList() {
  const qc = useQueryClient();
  const { status } = useAuth();
  const admin = status?.user?.is_admin ?? false;
  const { data, isError } = useModules();
  const save = useMutation({
    mutationFn: (change: Partial<Modules>) => request<Modules>("PUT", "/api/modules", change),
    onSuccess: (mods) => {
      qc.setQueryData(MODULES_KEY, mods);
      // Listy zależne od modułów (urządzenia, pulpit) od razu bez wyłączonych
      return Promise.all([qc.invalidateQueries({ queryKey: ["devices"] }), qc.invalidateQueries({ queryKey: ["dashboard"] })]);
    },
  });
  return (
    <>
      {isError && <ErrorNote>{t("mod.loadError")}</ErrorNote>}
      {data && (
        <Card>
          <ul className="divide-y divide-border">
            {MODULE_IDS.map((id) => {
              const { icon: ModIcon, label, desc } = META[id];
              const on = data[id];
              return (
                <li key={id} className="flex items-center gap-3 px-4 py-3">
                  <ModIcon size={22} aria-hidden="true" className="shrink-0 text-text-2" />
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium">{t(label)}</p>
                    <p className="text-xs text-text-2">{t(desc)}</p>
                  </div>
                  <span className={`rounded-md px-2 py-0.5 text-xs ${on ? "bg-success-soft text-success" : "bg-surface-2 text-text-2"}`}>
                    {t(on ? "mod.on" : "mod.off")}
                  </span>
                  <Toggle checked={on} disabled={!admin || save.isPending} label={t(label)} onChange={(v) => save.mutate({ [id]: v })} />
                </li>
              );
            })}
          </ul>
        </Card>
      )}
      {save.isError && (
        <div className="mt-3">
          <ErrorNote>{save.error instanceof ApiError ? save.error.message : t("auth.error.generic")}</ErrorNote>
        </div>
      )}
    </>
  );
}

/** Ustawienia → Moduły: włączanie integracji. Wyłączony moduł znika z panelu i nie działa w kolektorze. */
export function ModulesPage() {
  const { status } = useAuth();
  const admin = status?.user?.is_admin ?? false;
  const { data } = useModules();
  const count = data ? MODULE_IDS.filter((m) => data[m]).length : null;

  return (
    <>
      <PageHeader title={t("settings.modules.title")}>
        {count != null && <span className="text-sm text-text-2">{t("mod.count", { n: count, total: MODULE_IDS.length })}</span>}
      </PageHeader>
      <p className="mb-4 max-w-prose text-sm text-text-2">{t("mod.intro")}</p>
      <ModuleList />
      <p className="mt-4 max-w-prose text-xs text-text-2">{admin ? t("mod.hint") : t("mod.adminOnly")}</p>
    </>
  );
}
