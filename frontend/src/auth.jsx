import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { apiGet, apiPost, onAuthLost, refreshSession, setAccessToken } from "./api.js";

const AuthCtx = createContext(null);

export function useAuth() {
  const value = useContext(AuthCtx);
  if (!value) throw new Error("useAuth must be used inside <AuthProvider>");
  return value;
}

export { AuthCtx };

export function AuthProvider({ children }) {
  const [status, setStatus] = useState("booting"); // booting | authed | anon
  const [user, setUser] = useState(null);
  const [auth, setAuth] = useState(null); // non-secret /auth/status payload

  const refreshAuthStatus = useCallback(async () => {
    try {
      const st = await apiGet("/auth/status");
      setAuth(st);
      return st;
    } catch {
      return null;
    }
  }, []);

  const becomeAnon = useCallback(() => {
    setAccessToken(null);
    setUser(null);
    setStatus("anon");
  }, []);

  useEffect(() => {
    let alive = true;
    (async () => {
      // Silent bootstrap: an HttpOnly refresh cookie survives reloads. Try a
      // lightweight refresh, then confirm the account via /me.
      const body = await refreshSession();
      if (!alive) return;
      if (body?.access_token) {
        try {
          const me = await apiGet("/auth/me");
          if (!alive) return;
          setUser(me.user);
          setStatus("authed");
        } catch {
          if (alive) becomeAnon();
        }
      } else {
        if (alive) becomeAnon();
      }
      refreshAuthStatus();
    })();
    const off = onAuthLost(() => {
      if (alive) {
        becomeAnon();
        refreshAuthStatus();
      }
    });
    return () => {
      alive = false;
      off();
    };
  }, [becomeAnon, refreshAuthStatus]);

  const signIn = useCallback(
    async (username, password) => {
      const body = await apiPost("/auth/login", { username, password });
      setAccessToken(body.access_token);
      const me = await apiGet("/auth/me");
      setUser(me.user);
      setStatus("authed");
      refreshAuthStatus();
      return me.user;
    },
    [refreshAuthStatus]
  );

  const signUp = useCallback(async (username, password, displayName) => {
    const body = await apiPost("/auth/register", {
      username,
      password,
      display_name: displayName ?? "",
    });
    refreshAuthStatus();
    return body;
  }, [refreshAuthStatus]);

  const signOut = useCallback(async () => {
    try {
      await apiPost("/auth/logout");
    } finally {
      becomeAnon();
      refreshAuthStatus();
    }
  }, [becomeAnon, refreshAuthStatus]);

  const value = useMemo(
    () => ({
      status,
      user,
      auth,
      isAdmin: user?.role === "admin",
      canMutate: user?.role === "admin" || user?.role === "analyst",
      signIn,
      signUp,
      signOut,
    }),
    [status, user, auth, signIn, signUp, signOut]
  );

  return <AuthCtx.Provider value={value}>{children}</AuthCtx.Provider>;
}