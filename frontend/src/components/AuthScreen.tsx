import { LoaderCircle, LogIn, UserPlus } from "lucide-react";
import { FormEvent, useState } from "react";

import { getCurrentUser, loginUser, registerUser } from "../api/auth";
import { ApiError } from "../api/client";
import type { AuthUser } from "../types/auth";


interface AuthScreenProps {
  onAuthenticated: (token: string, user: AuthUser) => void;
}

type AuthMode = "login" | "register";

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return error.message;
  }
  return "认证请求失败，请稍后重试。";
}

export function AuthScreen({ onAuthenticated }: AuthScreenProps) {
  const [mode, setMode] = useState<AuthMode>("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function switchMode(nextMode: AuthMode) {
    setMode(nextMode);
    setError(null);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) {
      return;
    }

    const credentials = { username: username.trim(), password };
    setBusy(true);
    setError(null);
    try {
      const registeredUser =
        mode === "register" ? await registerUser(credentials) : null;
      const tokenResponse = await loginUser(credentials);
      const user =
        registeredUser ?? (await getCurrentUser(tokenResponse.access_token));
      onAuthenticated(tokenResponse.access_token, user);
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="auth-page">
      <section className="auth-panel" aria-labelledby="auth-title">
        <div className="auth-brand">
          <span className="brand-mark" aria-hidden="true">
            {mode === "login" ? <LogIn size={22} /> : <UserPlus size={22} />}
          </span>
          <div>
            <p>AI CONTENT DESK</p>
            <h1 id="auth-title">AI 内容运营智能体</h1>
          </div>
        </div>

        <div className="auth-tabs" role="tablist" aria-label="认证方式">
          <button
            type="button"
            role="tab"
            aria-selected={mode === "login"}
            className={mode === "login" ? "is-active" : ""}
            onClick={() => switchMode("login")}
          >
            登录
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={mode === "register"}
            className={mode === "register" ? "is-active" : ""}
            onClick={() => switchMode("register")}
          >
            注册
          </button>
        </div>

        <form className="auth-form" onSubmit={handleSubmit}>
          <label htmlFor="auth-username">用户名</label>
          <input
            id="auth-username"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            minLength={3}
            maxLength={50}
            autoComplete="username"
            disabled={busy}
            required
          />

          <label htmlFor="auth-password">密码</label>
          <input
            id="auth-password"
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            minLength={8}
            maxLength={128}
            autoComplete={mode === "login" ? "current-password" : "new-password"}
            disabled={busy}
            required
          />

          {error ? <div className="auth-error" role="alert">{error}</div> : null}

          <button className="button button-primary auth-submit" type="submit" disabled={busy}>
            {busy ? (
              <LoaderCircle className="spin" size={18} aria-hidden="true" />
            ) : mode === "login" ? (
              <LogIn size={18} aria-hidden="true" />
            ) : (
              <UserPlus size={18} aria-hidden="true" />
            )}
            {busy ? "正在验证" : mode === "login" ? "登录" : "注册并登录"}
          </button>
        </form>
      </section>
    </main>
  );
}
