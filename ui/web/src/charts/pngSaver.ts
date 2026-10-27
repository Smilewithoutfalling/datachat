// 阶段 6 收尾：桌面端导出 PNG（S 10-27 本机试装：WebView2 里 data URL + <a download> 点了没反应，壳里没有下载处理器）。
// 桌面壳里由 Shell 注册一个 saver：把 PNG 字节 POST /exports/png，后端写进「下载」文件夹并返回完整路径（app/server/exports.py）。
// 浏览器模式不注册，EChart 照旧走 exportPng.download（<a download>）。模块级单例：EChart 不持有 client，免得为一个按钮
// 把 client 穿过 TurnView → EChart 三层 props。
export type PngSaver = (dataUrl: string, filename: string) => Promise<string>;

let saver: PngSaver | null = null;

export function setPngSaver(s: PngSaver | null): void {
  saver = s;
}

export function getPngSaver(): PngSaver | null {
  return saver;
}

/** data:image/png;base64,… → 字节。不用 fetch(dataUrl)：connect-src 'self' 会拦 data:（exportPng.ts 头注释，实测）。 */
export function dataUrlBytes(dataUrl: string): Uint8Array {
  const m = /^data:image\/png;base64,(.*)$/s.exec(dataUrl);
  if (!m) throw new Error("not a png data url");
  const bin = atob(m[1]);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}
