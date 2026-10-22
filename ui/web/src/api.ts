// 所有 API 调用的唯一出口：带 Bearer 头；遇到 401 统一转"会话已失效"页（后端重启换了 token、新标签页没有 token）。
export class Unauthorized extends Error {
  constructor() {
    super("token 无效或已失效");
    this.name = "Unauthorized";
  }
}

export class ApiError extends Error {
  constructor(public status: number, public detail: string) {
    super(`${status}: ${detail}`);
    this.name = "ApiError";
  }
}

type Listener = () => void;

export class Api {
  private listeners = new Set<Listener>();

  private native: boolean;

  constructor(private token: string | null, private fetchImpl?: typeof fetch) {
    this.native = !fetchImpl; // 测试注入 fetch 时，上传也走 fetch（拿不到进度）
    this.fetchImpl = fetchImpl ?? ((...a) => fetch(...a));
  }

  // <img src> 带不了请求头，图表 PNG 是唯一接受 ?token= 的接口（app/server/app.py auth）。只认后端给的 /charts/<name>。
  chartSrc(path: string): string | null {
    if (!this.token || !/^\/charts\/[^/?#]+$/.test(path)) return null;
    return `${path}?token=${encodeURIComponent(this.token)}`;
  }

  onUnauthorized(fn: Listener): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  async request(path: string, init: RequestInit = {}): Promise<Response> {
    if (!this.token) {
      this.listeners.forEach((fn) => fn());
      throw new Unauthorized();
    }
    const headers = new Headers(init.headers);
    headers.set("Authorization", `Bearer ${this.token}`);
    const res = await this.fetchImpl!(path, { ...init, headers, credentials: "omit", referrerPolicy: "no-referrer" });
    if (res.status === 401) {
      this.listeners.forEach((fn) => fn());
      throw new Unauthorized();
    }
    if (!res.ok) {
      let detail = res.statusText;
      try {
        const body = await res.json();
        detail = typeof body?.detail === "string" ? body.detail : JSON.stringify(body?.detail ?? body);
      } catch {
        /* 非 JSON 错误体 */
      }
      throw new ApiError(res.status, detail);
    }
    return res;
  }

  /** 上传带进度（phase5 V2a §6.3）：fetch 拿不到上传进度，改用 XHR。错误处理与 request 一致（401 → 失效页）。 */
  async upload<T>(path: string, body: FormData, onProgress?: (p: number) => void): Promise<T> {
    if (!this.native || typeof XMLHttpRequest === "undefined") return this.json<T>(path, { method: "POST", body });
    if (!this.token) {
      this.listeners.forEach((fn) => fn());
      throw new Unauthorized();
    }
    const token = this.token;
    const xhr = new XMLHttpRequest();
    const done = new Promise<XMLHttpRequest>((resolve, reject) => {
      xhr.onload = () => resolve(xhr);
      xhr.onerror = () => reject(new TypeError("网络错误，上传没有完成"));
      xhr.onabort = () => reject(new TypeError("上传已取消"));
    });
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress?.(e.loaded / e.total);
    xhr.open("POST", path);
    xhr.setRequestHeader("Authorization", `Bearer ${token}`);
    xhr.send(body);
    await done;
    if (xhr.status === 401) {
      this.listeners.forEach((fn) => fn());
      throw new Unauthorized();
    }
    let parsed: unknown = null;
    try {
      parsed = JSON.parse(xhr.responseText);
    } catch {
      /* 非 JSON */
    }
    if (xhr.status < 200 || xhr.status >= 300) {
      const d = (parsed as { detail?: unknown } | null)?.detail;
      throw new ApiError(xhr.status, typeof d === "string" ? d : d !== undefined ? JSON.stringify(d) : xhr.statusText);
    }
    return parsed as T;
  }

  async json<T>(path: string, init: RequestInit = {}): Promise<T> {
    return (await this.request(path, init)).json() as Promise<T>;
  }
}
