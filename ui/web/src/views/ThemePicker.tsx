// F3 第四步：全局图表主题选择（存 localStorage，所有图立即 setTheme）。
import { useSyncExternalStore } from "react";
import { getChartTheme, setChartTheme, subscribeChartTheme, THEME_NAMES, THEMES } from "../charts/themes";

export function ThemePicker() {
  const theme = useSyncExternalStore(subscribeChartTheme, getChartTheme);
  return (
    <label className="theme-picker">
      图表主题
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
