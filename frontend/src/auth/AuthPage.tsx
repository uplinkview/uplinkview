import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Button, Card, ErrorNote, Field, Logo } from "../components/ui";
import { t } from "../i18n";
import { ApiError, post, type User } from "../lib/api";
import { AUTH_KEY } from "./AuthProvider";
import { PasswordRequirements } from "../components/PasswordRequirements";
import { MIN_PASSWORD } from "../lib/password";
import { LanguageSelect } from "../components/LanguageSelect";
import { SourceLink } from "../components/SourceLink";


/** Ekran logowania albo kreatora pierwszego konta (gdy w bazie nie ma jeszcze użytkowników). */
export function AuthPage({ mode }: { mode: "login" | "setup" }) {
  const qc = useQueryClient();
  const setup = mode === "setup";
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [repeat, setRepeat] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);
  // Drugi krok logowania: konto z logowaniem dwuskładnikowym (serwer odpowiada `totp_required`)
  const [needCode, setNeedCode] = useState(false);
  const [code, setCode] = useState("");

  const submit = useMutation({
    mutationFn: () =>
      post<User>(setup ? "/api/auth/setup" : "/api/auth/login", { username, password, ...(needCode && code.trim() ? { code: code.trim() } : {}) }),
    onError: (err) => {
      if (err instanceof ApiError && err.code === "totp_required") setNeedCode(true);
      if (err instanceof ApiError && err.code === "totp_invalid") setCode("");
    },
    onSuccess: () => {
      // Po założeniu konta panel otwiera się na kreatorze pierwszej konfiguracji (pierwsze urządzenie)
      if (setup) window.history.replaceState(null, "", "/setup");
      return qc.invalidateQueries({ queryKey: AUTH_KEY });
    },
  });

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    setLocalError(null);
    if (setup) {
      if (password.length < MIN_PASSWORD) return setLocalError(t("auth.error.short"));
      if (password !== repeat) return setLocalError(t("auth.error.mismatch"));
    }
    submit.mutate();
  }

  const askedForCode = submit.error instanceof ApiError && submit.error.code === "totp_required";
  const serverError = submit.error && !askedForCode
    ? submit.error instanceof ApiError
      ? submit.error.message
      : t("auth.error.generic")
    : null;
  const error = localError ?? serverError;

  return (
    <main className="flex min-h-full items-center justify-center p-4">
      <Card className="w-full max-w-sm p-6">
        <div className="mb-5 flex items-center gap-3">
          <Logo size={36} />
          <div>
            <p className="text-sm font-medium text-text-2">{t("app.name")}</p>
            <h1 className="text-xl font-medium leading-tight">{setup ? t("auth.setup.title") : t("auth.login.title")}</h1>
          </div>
        </div>
        <p className="mb-5 text-sm text-text-2">{setup ? t("auth.setup.subtitle") : t("auth.login.subtitle")}</p>

        <form onSubmit={onSubmit} className="flex flex-col gap-4" noValidate>
          <Field
            id="username"
            label={t("auth.username")}
            autoComplete="username"
            autoFocus={!needCode}
            required
            readOnly={needCode}
            value={username}
            onChange={(e) => setUsername(e.target.value)}
          />
          <Field
            id="password"
            label={t("auth.password")}
            type="password"
            autoComplete={setup ? "new-password" : "current-password"}
            required
            readOnly={needCode}
            aria-describedby={setup ? "password-rules" : undefined}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          {needCode && (
            <>
              <Field
                id="totp-code"
                label={t("auth.code")}
                inputMode="text"
                autoComplete="one-time-code"
                autoFocus
                maxLength={32}
                hint={t("auth.code.hint")}
                value={code}
                onChange={(e) => setCode(e.target.value)}
              />
              <button
                type="button"
                className="self-start text-xs text-text-2 underline-offset-2 hover:underline"
                onClick={() => {
                  setNeedCode(false);
                  setCode("");
                  submit.reset();
                }}
              >
                {t("auth.code.back")}
              </button>
            </>
          )}
          {setup && <PasswordRequirements id="password-rules" password={password} />}
          {setup && (
            <Field
              id="repeat"
              label={t("auth.password.repeat")}
              type="password"
              autoComplete="new-password"
              required
              value={repeat}
              onChange={(e) => setRepeat(e.target.value)}
            />
          )}
          {error && <ErrorNote>{error}</ErrorNote>}
          <Button type="submit" variant="primary" disabled={submit.isPending || !username || !password || (needCode && !code.trim())}>
            {submit.isPending
              ? setup
                ? t("auth.setup.busy")
                : t("auth.login.busy")
              : setup
                ? t("auth.setup.submit")
                : t("auth.login.submit")}
          </Button>
        </form>
        <div className="mt-5 flex items-center justify-between gap-3">
          <SourceLink />
          <LanguageSelect compact />
        </div>
      </Card>
    </main>
  );
}
