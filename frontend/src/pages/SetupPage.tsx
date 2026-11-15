import { IconCheck, IconCircleCheck, IconPlus } from "@tabler/icons-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router";
import { Button, Card, PageHeader } from "../components/ui";
import { KIND_LABEL, deviceIcon } from "../components/widgets/DevicesWidget";
import { t, type TextKey } from "../i18n";
import type { Device } from "../lib/api";
import { MODULE_IDS, useModules } from "../lib/modules";
import { useDevices } from "../lib/queries";
import { DeviceForm } from "./settings/devices/DeviceForm";
import { DiscoveryPanel } from "./settings/devices/DiscoveryPanel";
import { ModuleList } from "./settings/ModulesPage";

const STEPS: TextKey[] = ["setup.step.welcome", "setup.step.devices", "setup.step.modules", "setup.step.done"];

function Stepper({ step }: { step: number }) {
  return (
    <ol aria-label={t("setup.progress")} className="mb-5 flex flex-wrap gap-2">
      {STEPS.map((label, i) => (
        <li
          key={label}
          aria-current={i === step ? "step" : undefined}
          className={`flex items-center gap-2 rounded-full px-3 py-1 text-xs ${
            i === step ? "bg-accent-soft font-medium text-accent-text" : i < step ? "bg-success-soft text-success" : "bg-surface-2 text-text-2"
          }`}
        >
          {i < step ? <IconCheck size={14} aria-hidden="true" /> : <span aria-hidden="true">{i + 1}</span>}
          {t(label)}
        </li>
      ))}
    </ol>
  );
}

function Welcome({ onNext }: { onNext: () => void }) {
  return (
    <Card className="max-w-2xl p-5">
      <h2 className="text-base font-medium">{t("setup.welcome.title")}</h2>
      <p className="mt-2 text-sm text-text-2">{t("setup.welcome.body")}</p>
      <ul className="mt-4 flex flex-col gap-2 text-sm">
        {(["setup.welcome.need1", "setup.welcome.need2", "setup.welcome.need3"] as const).map((k) => (
          <li key={k} className="flex gap-2">
            <IconCircleCheck size={18} aria-hidden="true" className="mt-0.5 shrink-0 text-accent-text" />
            {t(k)}
          </li>
        ))}
      </ul>
      <div className="mt-5 flex flex-wrap gap-2">
        <Button variant="primary" onClick={onNext}>
          {t("setup.start")}
        </Button>
        <Link to="/" className="inline-flex items-center rounded-lg px-3.5 py-2 text-sm text-text-2 hover:bg-surface-2 hover:text-text">
          {t("setup.skip")}
        </Link>
      </div>
    </Card>
  );
}

function DeviceRow({ device }: { device: Device }) {
  const Icon = deviceIcon(device.kind);
  return (
    <li className="flex items-center gap-3 px-4 py-2.5 text-sm">
      <Icon size={20} aria-hidden="true" className="shrink-0 text-text-2" />
      <span className="min-w-0 flex-1 truncate font-medium">{device.name}</span>
      <span className="shrink-0 text-xs text-text-2">
        {device.host} · {t(KIND_LABEL[device.kind] ?? "dash.kind.other")}
      </span>
    </li>
  );
}

function Devices({ onNext, onBack }: { onNext: () => void; onBack: () => void }) {
  const devices = useDevices();
  const list = devices.data ?? [];
  // Nowy formularz po każdym zapisie (klucz), a po pierwszym urządzeniu – dopiero na życzenie
  const [formKey, setFormKey] = useState(0);
  const [adding, setAdding] = useState(false);
  const [lastAdded, setLastAdded] = useState<string | null>(null);
  const showForm = adding;
  return (
    <div className="grid max-w-5xl gap-4 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
      <div className="flex flex-col gap-3">
        <p className="text-sm text-text-2">{t("setup.devices.intro")}</p>
        <DiscoveryPanel onAdded={(added) => setLastAdded(added.map((d) => d.name).join(", "))} />
        {lastAdded && (
          <p role="status" className="rounded-lg bg-success-soft px-3 py-2 text-sm text-success">
            {t("setup.devices.added", { name: lastAdded })}
          </p>
        )}
        {showForm ? (
          <DeviceForm
            key={formKey}
            inline
            onClose={() => setAdding(false)}
            onSaved={(d) => {
              setLastAdded(d.name);
              setAdding(false);
              setFormKey((k) => k + 1);
            }}
          />
        ) : (
          <Button className="self-start" onClick={() => setAdding(true)}>
            <IconPlus size={16} aria-hidden="true" />
            {list.length ? t("setup.devices.another") : t("setup.devices.manual")}
          </Button>
        )}
      </div>
      <div className="flex flex-col gap-3">
        <Card>
          <h2 className="px-4 pt-3 text-sm font-medium">{t("setup.devices.list", { n: list.length })}</h2>
          {list.length === 0 ? (
            <p className="px-4 py-3 text-sm text-text-2">{t("setup.devices.none")}</p>
          ) : (
            <ul className="divide-y divide-border">
              {list.map((d) => (
                <DeviceRow key={d.id} device={d} />
              ))}
            </ul>
          )}
        </Card>
        <p className="text-xs text-text-2">{t("setup.devices.tip")}</p>
        <div className="flex flex-wrap gap-2">
          <Button onClick={onBack}>{t("setup.back")}</Button>
          <Button variant="primary" onClick={onNext}>
            {list.length ? t("setup.next") : t("setup.devices.later")}
          </Button>
        </div>
      </div>
    </div>
  );
}

function Modules({ onNext, onBack }: { onNext: () => void; onBack: () => void }) {
  return (
    <div className="flex max-w-2xl flex-col gap-3">
      <p className="text-sm text-text-2">{t("setup.modules.intro")}</p>
      <ModuleList />
      <p className="text-xs text-text-2">{t("setup.modules.later")}</p>
      <div className="flex flex-wrap gap-2">
        <Button onClick={onBack}>{t("setup.back")}</Button>
        <Button variant="primary" onClick={onNext}>
          {t("setup.next")}
        </Button>
      </div>
    </div>
  );
}

const NEXT_STEPS: { to: string; label: TextKey; module?: "unifi" | "agents" }[] = [
  { to: "/settings/controllers", label: "setup.done.unifi", module: "unifi" },
  { to: "/settings/agents", label: "setup.done.agents", module: "agents" },
  { to: "/settings/alert-rules", label: "setup.done.alerts" },
  { to: "/settings/notifications", label: "setup.done.notifications" },
];

function Done() {
  const navigate = useNavigate();
  const devices = useDevices().data ?? [];
  const mods = useModules().data;
  const on = mods ? MODULE_IDS.filter((m) => mods[m]).length : 0;
  return (
    <Card className="max-w-2xl p-5">
      <h2 className="flex items-center gap-2 text-base font-medium">
        <IconCircleCheck size={22} aria-hidden="true" className="text-success" />
        {t("setup.done.title")}
      </h2>
      <p className="mt-2 text-sm text-text-2">{t("setup.done.summary", { devices: devices.length, modules: on })}</p>
      <p className="mt-4 text-sm font-medium">{t("setup.done.next")}</p>
      <ul className="mt-2 flex flex-col gap-1.5 text-sm">
        {NEXT_STEPS.filter((s) => !s.module || mods?.[s.module]).map((s) => (
          <li key={s.to}>
            <Link to={s.to} className="text-accent-text hover:underline">
              {t(s.label)}
            </Link>
          </li>
        ))}
      </ul>
      <Button variant="primary" className="mt-5" onClick={() => navigate("/")}>
        {t("setup.done.go")}
      </Button>
    </Card>
  );
}

/** Kreator pierwszej konfiguracji: powitanie → pierwsze urządzenia (test SNMP w panelu) → integracje → gotowe.
 * Otwiera się sam po założeniu konta; później z pustego pulpitu albo spod adresu /setup. */
export function SetupPage() {
  const [step, setStep] = useState(0);
  const next = () => setStep((s) => Math.min(STEPS.length - 1, s + 1));
  const back = () => setStep((s) => Math.max(0, s - 1));
  return (
    <>
      <PageHeader title={t("setup.title")} />
      <Stepper step={step} />
      {step === 0 && <Welcome onNext={next} />}
      {step === 1 && <Devices onNext={next} onBack={back} />}
      {step === 2 && <Modules onNext={next} onBack={back} />}
      {step === 3 && <Done />}
    </>
  );
}
