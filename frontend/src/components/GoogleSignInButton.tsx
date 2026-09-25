"use client";

import { useCallback, useEffect, useRef, useState } from "react";

declare global {
  interface Window {
    google?: {
      accounts: {
        id: {
          initialize: (cfg: Record<string, unknown>) => void;
          renderButton: (el: HTMLElement, cfg: Record<string, unknown>) => void;
          prompt: () => void;
          disableAutoSelect: () => void;
        };
      };
    };
  }
}

type Props = {
  clientId: string;
  onCredential: (credential: string) => void;
  disabled?: boolean;
};

export function GoogleSignInButton({ clientId, onCredential, disabled }: Props) {
  const hostRef = useRef<HTMLDivElement>(null);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const cbRef = useRef(onCredential);
  cbRef.current = onCredential;

  const mountButton = useCallback(() => {
    if (!hostRef.current || !window.google?.accounts?.id || !clientId) return;
    hostRef.current.innerHTML = "";
    window.google.accounts.id.initialize({
      client_id: clientId,
      callback: (response: { credential?: string }) => {
        if (response.credential) cbRef.current(response.credential);
      },
      auto_select: false,
      cancel_on_tap_outside: true,
    });
    window.google.accounts.id.renderButton(hostRef.current, {
      theme: "outline",
      size: "large",
      text: "signin_with",
      shape: "rectangular",
      logo_alignment: "left",
      width: 220,
    });
    setReady(true);
  }, [clientId]);

  useEffect(() => {
    if (!clientId || disabled) return;
    let cancelled = false;

    const existing = document.querySelector<HTMLScriptElement>(
      'script[data-google-gsi="1"]',
    );
    if (existing && window.google?.accounts?.id) {
      mountButton();
      return;
    }

    const script =
      existing ||
      Object.assign(document.createElement("script"), {
        src: "https://accounts.google.com/gsi/client",
        async: true,
      });
    script.dataset.googleGsi = "1";

    const onLoad = () => {
      if (!cancelled) mountButton();
    };
    const onError = () => {
      if (!cancelled) setError("Could not load Google Sign-In");
    };

    if (!existing) {
      script.addEventListener("load", onLoad);
      script.addEventListener("error", onError);
      document.head.appendChild(script);
    } else {
      existing.addEventListener("load", onLoad);
    }

    return () => {
      cancelled = true;
      script.removeEventListener("load", onLoad);
      script.removeEventListener("error", onError);
    };
  }, [clientId, disabled, mountButton]);

  if (disabled) return null;

  return (
    <div className="flex flex-col items-end gap-1">
      <div ref={hostRef} className={ready ? "" : "min-h-[40px] min-w-[220px]"} />
      {!ready && !error && (
        <span className="text-[10px] text-stone-500">Loading Google…</span>
      )}
      {error && <span className="text-[10px] text-amber-800">{error}</span>}
    </div>
  );
}
