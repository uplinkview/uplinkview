import { t } from "../i18n";

/** Repozytorium z kodem źródłowym (AGPL-3.0, § 13: użytkownicy przez sieć dostają dostęp do kodu). */
export const SOURCE_URL = "https://github.com/uplinkview/uplinkview";
export const LICENSE_NAME = "AGPL-3.0";

/** Mały link „AGPL-3.0 · Kod źródłowy” – w menu i na stronie logowania. */
export function SourceLink({ className = "" }: { className?: string }) {
  return (
    <a
      href={SOURCE_URL}
      target="_blank"
      rel="noopener noreferrer"
      className={`text-[11px] text-muted underline-offset-2 hover:text-text hover:underline ${className}`}
    >
      {t("source.link", { license: LICENSE_NAME })}
    </a>
  );
}
