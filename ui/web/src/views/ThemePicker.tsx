// F3 第四步：全局图表主题选择（存 localStorage，所有图立即 setTheme）。V2a：顶栏胶囊「主题 经典 ▾」。
import { useSyncExternalStore } from "react";
import { getChartTheme, setChartTheme, subscribeChartTheme, THEME_NAMES, THEMES } from "../charts/themes";
import { IconPalette } from "./icons";

export function ThemePicker() {
  const theme = useSyncExternalStore(subscribeChartTheme, getChartTheme);
  // 验收术语统一：这个东西全产品只叫「主题」（顶栏这里、文档里都是），不叫样式、不叫配色
  return (
    <label className="theme-picker pill">
      <IconPalette size={13} />
      主题

      <select aria-label="图表主题" value={theme} onChange={(e) => setChartTheme(e.target.value)}>
        {THEME_NAMES.map((n) => (
          <option key={n} value={n}>
            {THEMES[n].label}
          </option>
        ))}
      </select>
    </label>
  );
}
