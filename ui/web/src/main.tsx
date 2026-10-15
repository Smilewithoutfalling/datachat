import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { Api } from "./api";
import { takeToken } from "./token";

// 必须在任何 await / 渲染之前：读出 fragment 里的 token 并同步抹掉地址栏
const api = new Api(takeToken());

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App api={api} />
  </StrictMode>,
);
