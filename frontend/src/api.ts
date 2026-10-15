let csrf = "";
export async function api<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`/api${path}`, {
    credentials: "same-origin",
    ...(body !== undefined
      ? {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-AutoDev-CSRF": csrf,
          },
          body: JSON.stringify(body),
        }
      : {}),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    const detail =
      typeof data.detail === "string"
        ? data.detail
        : "Please check the form values and try again.";
    throw new Error(detail);
  }
  return response.json();
}
export async function session() {
  csrf = (await api<{ csrf: string }>("/session")).csrf;
}
